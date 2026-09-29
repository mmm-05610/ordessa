"""The mem0 self-hosted stack provisioner and lifecycle (MB-2/MB-3).

What this module owns:

* **Prerequisite detection** — Docker and compose v2 are hard prerequisites
  (the pinned upstream deploys only via docker compose). Missing either is a
  typed ``ProvisioningUnsupported`` with the precise reason: the provisioner
  never fakes a local implementation to impersonate the stack (dispatch
  constraint 2).
* **Credential generation** — ``.env`` with fresh random
  ``POSTGRES_PASSWORD``/``ADMIN_API_KEY``/``JWT_SECRET``, ``MEM0_TELEMETRY=false``
  forced (pinned upstream default is ``true`` — F7), ports taken from the
  product's port plan (never hardcoded), written 0600 into the deploy
  directory under the product data root. Secrets live only there; nothing
  enters the repo or the Profile.
* **Compose 子栈 rendering** — a byte-stable, product-owned compose file
  with exactly two services (server + postgres; the dashboard is never
  started — the product manages memory over REST), binding the pinned
  upstream checkout from the data-root vendor directory (upstream code is
  never copied into this repo) and keeping all state (postgres data,
  history) in data-root directories.
* **Lifecycle** — up / stop / health (``GET /docs``) / upgrade (backup
  first, then migrate) / uninstall (stop and remove containers; the data
  directory is kept — memory outlives the stack).

All host effects go through the injected :class:`CommandRunner` and explicit
paths, so tests drive every branch with recorded fakes and no real Docker.
"""
from __future__ import annotations

import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import common, llm_wiring

#: deploy layout under the plugin's data-root directory
DEPLOY_DIR_NAME = "deploy"
VENDOR_DIR_NAME = "vendor"
POSTGRES_DATA_DIR_NAME = "postgres-data"
HISTORY_DIR_NAME = "history"
BACKUPS_DIR_NAME = "backups"
ENV_FILE_NAME = ".env"
COMPOSE_FILE_NAME = "docker-compose.ordessa-memory.yml"
VENDOR_SHA_FILE = "VENDOR_SHA"


class ProvisioningUnsupported(Exception):
    """A hard prerequisite is missing; the honest report, never a fake."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class PortPlan:
    """The two host ports the product's configuration assigns. The
    provisioner takes them as facts; it never picks defaults from the
    upstream documentation numbers."""

    server_port: int
    postgres_port: int

    def __post_init__(self) -> None:
        for name, value in (("server_port", self.server_port),
                            ("postgres_port", self.postgres_port)):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
                raise ValueError(f"{name} must be a TCP port from the product's port plan")


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


#: The runner seam: every docker/git effect funnels through here.
CommandRunner = Callable[[tuple[str, ...], float], CommandResult]


class SystemRunner:
    """The production runner: one bounded subprocess per call."""

    def __call__(self, argv: tuple[str, ...], timeout: float) -> CommandResult:
        completed = subprocess.run(
            list(argv), capture_output=True, text=True, timeout=timeout, check=False)
        return CommandResult(tuple(argv), completed.returncode,
                             completed.stdout, completed.stderr)


def detect_docker(runner: CommandRunner) -> dict[str, str]:
    """Detect Docker + compose v2; raise ``ProvisioningUnsupported`` with the
    precise missing piece otherwise (honest unsupported — dispatch
    constraint 2)."""
    docker = _detect_binary(runner, ("docker", "--version"))
    compose = runner(("docker", "compose", "version", "--short"), 15.0)
    if compose.returncode != 0:
        raise ProvisioningUnsupported(
            "Docker Compose v2 不可用（`docker compose version` 失败）；mem0 自托管栈"
            "仅支持 docker compose 部署，置备器不会用本地假实现冒充。原因："
            + (compose.stderr.strip() or compose.stdout.strip() or "unknown"))
    version = (compose.stdout.strip() or "v2")
    return {"docker": docker, "compose": version}


def _detect_binary(runner: CommandRunner, argv: tuple[str, ...]) -> str:
    try:
        result = runner(argv, 15.0)
    except (FileNotFoundError, OSError) as exc:
        raise ProvisioningUnsupported(
            f"Docker 前置缺失（{' '.join(argv[:1])} 不可执行：{exc}）；mem0 自托管栈"
            "仅支持 docker compose 部署，置备器不会用本地假实现冒充") from exc
    if result.returncode != 0:
        raise ProvisioningUnsupported(
            f"Docker 前置缺失（{' '.join(argv)} 退出码 {result.returncode}）；"
            "mem0 自托管栈仅支持 docker compose 部署，置备器不会用本地假实现冒充")
    return result.stdout.strip()


# -- vendor checkout -----------------------------------------------------------


def vendor_dir(data_root_dir: Path) -> Path:
    return Path(data_root_dir) / VENDOR_DIR_NAME / "mem0"


def ensure_vendor(runner: CommandRunner, data_root_dir: Path) -> Path:
    """The pinned upstream checkout under the data root (never inside the
    repo). An existing checkout at the wrong SHA is an honest refusal — the
    provisioner never silently repins someone's checkout."""
    target = vendor_dir(data_root_dir)
    sha_file = target / VENDOR_SHA_FILE
    if sha_file.exists():
        recorded = sha_file.read_text(encoding="utf-8").strip()
        if recorded != common.MEM0_GIT_SHA:
            raise ProvisioningUnsupported(
                f"vendor checkout 记录的 SHA {recorded[:12]}… 与本包 pin "
                f"{common.MEM0_GIT_SHA[:12]}… 不一致；升级须走显式 upgrade 流程，"
                "置备器不静默换版")
        return target
    target.mkdir(parents=True, exist_ok=True)
    clone = runner(("git", "clone", "--depth", "1", common.MEM0_REPO_URL,
                    str(target / "checkout")), 600.0)
    if clone.returncode != 0:
        raise ProvisioningUnsupported(
            "vendor checkout 克隆失败（" + (clone.stderr.strip()[-200:] or "unknown") + "）")
    fetch = runner(("git", "-C", str(target / "checkout"), "fetch", "--depth", "1",
                    "origin", common.MEM0_GIT_SHA), 600.0)
    checkout = runner(("git", "-C", str(target / "checkout"), "checkout", "FETCH_HEAD"), 60.0)
    if fetch.returncode != 0 or checkout.returncode != 0:
        raise ProvisioningUnsupported(
            "vendor checkout 无法对齐 pin SHA " + common.MEM0_GIT_SHA[:12] + "…："
            + (fetch.stderr.strip()[-200:] or checkout.stderr.strip()[-200:] or "unknown"))
    sha_file.write_text(common.MEM0_GIT_SHA + "\n", encoding="utf-8")
    return target


# -- .env generation ------------------------------------------------------------


def _fresh_secrets() -> dict[str, str]:
    return {
        "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
        "ADMIN_API_KEY": secrets.token_urlsafe(32),
        "JWT_SECRET": secrets.token_urlsafe(48),
    }


def render_env(port_plan: PortPlan, secrets_in: dict[str, str],
               key_rows: dict[str, str]) -> str:
    """The byte-stable ``.env`` text. ``key_rows`` carries the provider ENV
    key → credential REFERENCE rows (the caller resolves reference content
    before calling; this renderer never invents credentials)."""
    def row(key: str, value: object) -> str:
        return f"{key}={value if value is not None else ''}"

    lines = [
        "# Ordessa memory domain — generated .env (secrets; never commit, never copy)",
        f"# mem0 pin: {common.MEM0_REPO_URL} @ {common.MEM0_GIT_SHA}",
        "# 遥测已显式关闭（pinned 上游默认 true —— MEM0_TELEMETRY=false）",
        "",
        "# --- provider keys（来自 model-provider 解析的 bundled provider；无则留空）---",
    ]
    for env_key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        lines.append(row(env_key, key_rows.get(env_key, "")))
    lines += [
        "",
        "# --- Postgres（记忆/认证/向量一体；无替代后端）---",
        row("POSTGRES_HOST", "postgres"),
        row("POSTGRES_PORT", "5432"),
        row("POSTGRES_DB", "postgres"),
        row("POSTGRES_USER", "postgres"),
        row("POSTGRES_PASSWORD", secrets_in["POSTGRES_PASSWORD"]),
        row("POSTGRES_COLLECTION_NAME", "memories"),
        row("APP_DB_NAME", "mem0_app"),
        "",
        "# --- server auth（程序访问走 X-API-Key；只打印/写入一次）---",
        row("ADMIN_API_KEY", secrets_in["ADMIN_API_KEY"]),
        row("JWT_SECRET", secrets_in["JWT_SECRET"]),
        row("AUTH_DISABLED", "false"),
        "",
        "# --- 遥测：显式关闭（红线 4）---",
        row("MEM0_TELEMETRY", "false"),
        row("MEM0_TELEMETRY_STATE_PATH", "/app/history/telemetry.json"),
        "",
        "# --- 模型默认值（可被 POST /configure 覆盖）---",
        row("MEM0_DEFAULT_LLM_MODEL", "gpt-5-mini"),
        row("MEM0_DEFAULT_EMBEDDER_MODEL", "text-embedding-3-small"),
        "",
        f"# host ports assigned by the product port plan: server={port_plan.server_port} "
        f"postgres={port_plan.postgres_port} (container 内部端口固定 8000/5432)",
    ]
    return "\n".join(lines) + "\n"


def write_env(deploy_dir: Path, text: str) -> Path:
    """Write the ``.env`` 0600 into the deploy directory; refuse to write
    anywhere inside this package's own source tree (the deploy directory
    always lives under the product data root, outside the repo)."""
    deploy_dir = Path(deploy_dir)
    source_root = Path(__file__).resolve().parents[3]
    resolved = deploy_dir.resolve()
    if resolved == source_root or source_root in resolved.parents:
        raise ProvisioningUnsupported(
            "拒绝把 .env 写进插件源码树；部署目录必须在产品 data-root 下")
    deploy_dir.mkdir(parents=True, exist_ok=True)
    env_path = deploy_dir / ENV_FILE_NAME
    env_path.write_text(text, encoding="utf-8")
    env_path.chmod(0o600)
    return env_path


def read_admin_key(env_path: Path) -> str:
    """The admin key at call time, straight from the data-root ``.env``."""
    for line in Path(env_path).read_text(encoding="utf-8").splitlines():
        if line.startswith("ADMIN_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise ProvisioningUnsupported("deploy 目录的 .env 缺少 ADMIN_API_KEY 行；拒绝猜测")


# -- compose 子栈 -----------------------------------------------------------------


def render_compose(port_plan: PortPlan, data_root_dir: Path) -> str:
    """The byte-stable compose 子栈: exactly server + postgres (no
    dashboard — the product manages memory over REST)."""
    vendor = vendor_dir(Path(data_root_dir))
    pg_data = Path(data_root_dir) / POSTGRES_DATA_DIR_NAME
    history = Path(data_root_dir) / HISTORY_DIR_NAME
    lines = [
        "name: ordessa-memory",
        "",
        "services:",
        "  postgres:",
        f"    image: {common.POSTGRES_IMAGE}",
        "    restart: \"no\"",
        "    shm_size: \"128mb\"",
        "    environment:",
        "      - POSTGRES_USER=postgres",
        "      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must come from the generated .env}",
        "    healthcheck:",
        "      test: [\"CMD-SHELL\", \"pg_isready -q -U postgres\"]",
        "      interval: 5s",
        "      timeout: 5s",
        "      retries: 5",
        "    volumes:",
        f"      - {pg_data}:/var/lib/postgresql/data",
            "ports:",
        f"      - \"127.0.0.1:{port_plan.postgres_port}:5432\"",
        "  mem0:",
        "    build:",
        f"      context: {vendor}",
        "      dockerfile: server/Dockerfile",
        "    restart: \"no\"",
        "    env_file:",
        f"      - {Path(data_root_dir) / DEPLOY_DIR_NAME / ENV_FILE_NAME}",
        "    environment:",
        "      - MEM0_TELEMETRY=false",
        "      - POSTGRES_HOST=postgres",
        "      - POSTGRES_PORT=5432",
        "    depends_on:",
        "      postgres:",
        "        condition: service_healthy",
        "    volumes:",
        f"      - {history}:/app/history",
        "    ports:",
        f"      - \"127.0.0.1:{port_plan.server_port}:8000\"",
    ]
    return "\n".join(lines) + "\n"


# -- lifecycle ----------------------------------------------------------------


class MemoryStack:
    """The provisioned stack's lifecycle handle (MB-3)."""

    def __init__(self, runner: CommandRunner, data_root_dir: Path,
                 port_plan: PortPlan) -> None:
        self._runner = runner
        self._data_root = Path(data_root_dir)
        self._ports = port_plan
        self._deploy_dir = self._data_root / DEPLOY_DIR_NAME
        self._compose_file = self._deploy_dir / COMPOSE_FILE_NAME
        self._env_file = self._deploy_dir / ENV_FILE_NAME

    @property
    def deploy_dir(self) -> Path:
        return self._deploy_dir

    @property
    def env_file(self) -> Path:
        return self._env_file

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._ports.server_port}"

    def provision(self, key_rows: dict[str, str]) -> dict[str, str]:
        """Detect prerequisites → vendor checkout → generate secrets → write
        ``.env`` + compose file. Returns the non-secret facts (no key
        content ever leaves this method's ``.env`` write)."""
        facts = detect_docker(self._runner)
        ensure_vendor(self._runner, self._data_root)
        secrets_in = _fresh_secrets()
        env_text = render_env(self._ports, secrets_in, key_rows)
        write_env(self._deploy_dir, env_text)
        self._deploy_dir.mkdir(parents=True, exist_ok=True)
        self._compose_file.write_text(
            render_compose(self._ports, self._data_root), encoding="utf-8")
        return facts

    def up(self) -> CommandResult:
        self._require_provisioned()
        return self._runner(("docker", "compose", "-f", str(self._compose_file), "up", "-d"), 600.0)

    def stop(self) -> CommandResult:
        self._require_provisioned()
        return self._runner(("docker", "compose", "-f", str(self._compose_file), "stop"), 300.0)

    def ps(self) -> CommandResult:
        self._require_provisioned()
        return self._runner(("docker", "compose", "-f", str(self._compose_file), "ps"), 60.0)

    def backup(self, label: str) -> Path:
        """One ``pg_dumpall`` through the postgres service into the backups
        directory (upgrade's non-negotiable first step)."""
        self._require_provisioned()
        backups = self._data_root / BACKUPS_DIR_NAME
        backups.mkdir(parents=True, exist_ok=True)
        target = backups / f"mem0-{label}.sql"
        result = self._runner((
            "docker", "compose", "-f", str(self._compose_file), "exec", "-T", "postgres",
            "pg_dumpall", "-U", "postgres"), 600.0)
        if result.returncode != 0:
            raise ProvisioningUnsupported(
                "升级前备份失败（pg_dumpall 退出码 " + str(result.returncode) + "）；"
                "不备份不升级：" + result.stderr.strip()[-200:])
        target.write_text(result.stdout, encoding="utf-8")
        return target

    def upgrade(self, label: str) -> dict[str, str]:
        """Backup first, then re-align the vendor checkout to the pin, then
        bring the stack back up. Any failed step stops the upgrade honestly."""
        self._require_provisioned()
        backup_path = self.backup(label)
        self.stop()
        vendor = ensure_vendor(self._runner, self._data_root)
        up = self.up()
        if up.returncode != 0:
            raise ProvisioningUnsupported(
                "升级后启动失败：" + up.stderr.strip()[-200:])
        return {"backup": str(backup_path), "vendor": str(vendor)}

    def uninstall(self) -> CommandResult:
        """Stop and remove the containers; the data-root directories (postgres
        data, history, backups, .env) stay — memory outlives the stack."""
        self._require_provisioned()
        return self._runner((
            "docker", "compose", "-f", str(self._compose_file), "down", "--remove-orphans"), 300.0)

    def _require_provisioned(self) -> None:
        if not self._compose_file.exists() or not self._env_file.exists():
            raise ProvisioningUnsupported(
                "尚未置备（缺少生成的 compose/.env）；先执行 provision")
