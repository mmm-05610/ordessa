// C8 V03/V04 measurement for the temporary-Electron foundations gate: real
// Chromium layout and computed style inside the shipping Workbench shell, at two
// viewport widths. Nothing here is asserted from jsdom — the point of this module
// is that geometry, theme inheritance and stylesheet pollution are measured in the
// browser the product actually runs in.

const wait = ms => new Promise(resolve => setTimeout(resolve, ms))


export async function probeUiFoundations(win, width) {
  // A hidden smoke window can keep stale computed values after a variable change, and
  // this probe measures computed style; show it (without taking focus) for the measurement.
  if (!win.isVisible()) win.showInactive()
  // The shipping shell refuses to go below 760px; a narrow-viewport measurement has to
  // lift that floor for the duration of the probe, otherwise both "widths" clamp to 760.
  win.setMinimumSize(300, 400)
  win.setBounds({ x: win.getBounds().x, y: win.getBounds().y, width, height: 720 })
  await wait(250)
  return win.webContents.executeJavaScript(`(async () => {
    const nextFrame = () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const q = selector => document.querySelector(selector);
    const cs = element => getComputedStyle(element);
    const rect = element => { const r = element.getBoundingClientRect(); return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) }; };
    const box = element => ({ padding: cs(element).padding, background: cs(element).backgroundColor, border: cs(element).borderWidth, radius: cs(element).borderRadius, fontSize: cs(element).fontSize });
    const uiButton = q('[data-testid="ui-button"]'), foreign = q('[data-testid="foreign"]');
    const scroll = q('[data-testid="scroll"]'), panelBody = q('[data-testid="panel-body"]');
    const card = q('[data-testid="card"]'), input = q('[data-testid="ui-input"]');
    const missing = [['ui-button', uiButton], ['foreign', foreign], ['scroll', scroll], ['panel-body', panelBody], ['card', card], ['ui-input', input]]
      .filter(([, node]) => !node).map(([name]) => name);
    if (missing.length) return { missing };
    // Theme inheritance: the foundation consumes the host's semantic variables, so a
    // host-level override must reach it without the component redefining anything.
    // The primary variant paints with --ui-accent, which is what is overridden here.
    // Inheritance is proven from a host container above the control: the Workbench
    // region is the shell's own element, and a variable set there must reach the
    // foundation without the foundation redefining anything.
    const themeHost = uiButton.closest('[data-region]') || uiButton.parentElement;
    const beforeSurface = cs(uiButton).backgroundColor;
    themeHost.style.setProperty('--ui-accent', 'rgb(18, 52, 86)');
    // Two things must settle before the read is meaningful: the var() substitution of an
    // attached rule, and the control's own 120ms background-color transition.
    await new Promise(resolve => setTimeout(resolve, 220));
    const afterSurface = cs(uiButton).backgroundColor;
    const resolvedAfter = cs(uiButton).getPropertyValue('--ui-accent').trim();
    uiButton.style.setProperty('--ui-accent', 'rgb(9, 9, 9)');
    const localSurface = cs(uiButton).backgroundColor;
    uiButton.style.removeProperty('--ui-accent');
    themeHost.style.removeProperty('--ui-accent');
    // Pollution: disable only the foundations sheet and compare a foreign control with
    // the foundation button. The foreign control must not move at all; the foundation
    // button must fall back to the host's own bare-button rules.
    const sheet = [...document.styleSheets].find(candidate => {
      try { return [...(candidate.cssRules || [])].some(rule => rule.selectorText && rule.selectorText.includes('ods-ui-button')); }
      catch { return false; }
    }) || null;
    const foreignBefore = box(foreign);
    if (sheet) sheet.disabled = true;
    const uiWithoutSheet = box(uiButton);
    const foreignWithoutSheet = box(foreign);
    if (sheet) sheet.disabled = false;
    const foreignAfter = box(foreign);
    const uiWithSheet = box(uiButton);
    // Experiment: does custom-property substitution respond in this harness at all?
    const substitution = (() => {
      const node = document.createElement('div');
      node.style.background = 'var(--ui-accent, red)';
      themeHost.appendChild(node);
      const initial = getComputedStyle(node).backgroundColor;
      themeHost.style.setProperty('--ui-accent', 'rgb(18, 52, 86)');
      void node.offsetHeight;
      const changed = getComputedStyle(node).backgroundColor;
      themeHost.style.removeProperty('--ui-accent');
      node.remove();
      return { initial, changed };
    })();
    const header = q('[data-testid="panel-header"]') || card.querySelector('header');
    return {
      viewport: { width: window.innerWidth },
      pageOverflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      rects: { card: rect(card), panelBody: rect(panelBody), scroll: rect(scroll), uiButton: rect(uiButton) },
      scrollOwnsOverflow: cs(scroll).overflowY,
      panelBodyScrollable: cs(panelBody).overflowY,
      panelHeaderShrink: header ? cs(header).flexShrink : 'no header',
      scrollInnerOverflow: scroll.scrollWidth - scroll.clientWidth,
      themeFollowsHost: { beforeSurface, afterSurface, buttonClasses: uiButton.className,
        matchesPrimary: uiButton.matches('.ods-ui-button.ods-ui-button--primary'),
        accentVar: cs(uiButton).getPropertyValue('--ui-accent').trim(),
        computedBackground: cs(uiButton).background.slice(0, 60),
        resolvedAfter, localSurface, substitution,
        themeHostWas: themeHost ? themeHost.tagName + '.' + String(themeHost.className).slice(0, 30) : 'none' },
      loadedComponent: (q('[data-testid="availability"]') || {}).textContent || null,
      loadedInsideCard: card.textContent.includes('inside a Card'),
      pollution: { sheetFound: !!sheet, foreignBefore, foreignWithoutSheet, foreignAfter, uiWithSheet, uiWithoutSheet },
      draftValue: input.value,
      reducedMotion: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    };
  })()`)
}

/** Real keyboard order: focus one control, press Tab through the browser input stack. */
export async function tabForwardFrom(win, testId) {
  const before = await win.webContents.executeJavaScript(
    `(() => { const el = document.querySelector('[data-testid="${testId}"]'); if (!el) return 'missing'; el.focus(); return el.tagName + ':' + (el.getAttribute('data-testid') ?? ''); })()`)
  win.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Tab' })
  await wait(120)
  const after = await win.webContents.executeJavaScript(
    `document.activeElement ? document.activeElement.tagName + ':' + (document.activeElement.getAttribute('data-testid') ?? '') : 'none'`)
  return { before, after }
}
