"""Pi path leaf runs without kernel; standard-library-only retirement checks."""
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "src/ordessa_harness_pi/profile.py"

class RefuseKernel(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "pacthold" or fullname.startswith("pacthold."):
            raise AssertionError("Pi path configuration must not import kernel")

class ProfilePathRetirementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Isolate this leaf, not the not-yet-retired whole Harness dependency graph.
        guard = RefuseKernel(); sys.meta_path.insert(0, guard)
        name = "_ordessa_pi_profile_without_kernel"
        try:
            spec = importlib.util.spec_from_file_location(name, SOURCE)
            module = importlib.util.module_from_spec(spec); sys.modules[name] = module
            spec.loader.exec_module(module); cls.module = module
        finally:
            sys.meta_path.remove(guard)

    def test_configured_legacy_root_and_explicit_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict("os.environ", {"AGENT_BOX_HOME": str(root / "nested/../state")}):
                config = self.module.PiPluginConfig(binary="pi")
                self.assertEqual(config.resolved_agent_dir, root / "state/plugins/pi/agent")
                self.assertEqual(config.resolved_session_root, root / "state/plugins/pi/sessions")
                explicit = self.module.PiPluginConfig(binary="pi", agent_dir=root/"other-agent", session_root=root/"other-session")
                self.assertEqual(explicit.resolved_agent_dir, root/"other-agent")
                self.assertEqual(explicit.resolved_session_root, root/"other-session")
                self.assertFalse((root/"state").exists())

    def test_default_home_location_remains_historical(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict("os.environ", {"AGENT_BOX_HOME": ""}), patch.object(self.module.Path, "home", return_value=root):
                config = self.module.PiPluginConfig(binary="pi")
                self.assertEqual(config.resolved_agent_dir, root/".agent-box/plugins/pi/agent")
                self.assertEqual(config.resolved_session_root, root/".agent-box/plugins/pi/sessions")
                self.assertFalse((root/".agent-box").exists())

    def test_default_load_and_existing_unknown_key_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root/"plugins/pi/config.json";path.parent.mkdir(parents=True)
            with patch.dict("os.environ", {"AGENT_BOX_HOME": str(root)}):
                path.write_text(json.dumps({"binary":"pi", "model":"fixture"}))
                config = self.module.PiPluginConfig.load()
                self.assertEqual(config.source, path)
                self.assertEqual(config.model,"fixture")
                path.write_text(json.dumps({"unrecognized":True}))
                with self.assertRaises(self.module.PiConfigError):self.module.PiPluginConfig.load()

if __name__ == "__main__":
    unittest.main(verbosity=2)
