"""Browser helper scripts for apply prompts (kept out of prompt.py for slimming)."""

from __future__ import annotations

# Full-mode CAPTCHA detect (browser_evaluate body). Braces doubled for str.format.
CAPTCHA_DETECT_JS = r"""() => {{
  const r = {{}};
  const url = window.location.href;
  const hc = document.querySelector('.h-captcha, [data-hcaptcha-sitekey]');
  if (hc) {{
    r.type = 'hcaptcha'; r.sitekey = hc.dataset.sitekey || hc.dataset.hcaptchaSitekey;
  }}
  if (!r.type && document.querySelector('script[src*="hcaptcha.com"], iframe[src*="hcaptcha.com"]')) {{
    const el = document.querySelector('[data-sitekey]');
    if (el) {{ r.type = 'hcaptcha'; r.sitekey = el.dataset.sitekey; }}
  }}
  if (!r.type) {{
    const cf = document.querySelector('.cf-turnstile, [data-turnstile-sitekey]');
    if (cf) {{
      r.type = 'turnstile'; r.sitekey = cf.dataset.sitekey || cf.dataset.turnstileSitekey;
      if (cf.dataset.action) r.action = cf.dataset.action;
      if (cf.dataset.cdata) r.cdata = cf.dataset.cdata;
    }}
  }}
  if (!r.type && document.querySelector('script[src*="challenges.cloudflare.com"]')) {{
    r.type = 'turnstile_script_only'; r.note = 'Wait 3s and re-detect.';
  }}
  if (!r.type) {{
    const s = document.querySelector('script[src*="recaptcha"][src*="render="]');
    if (s) {{
      const m = s.src.match(/render=([^&]+)/);
      if (m && m[1] !== 'explicit') {{ r.type = 'recaptchav3'; r.sitekey = m[1]; }}
    }}
  }}
  if (!r.type) {{
    const rc = document.querySelector('.g-recaptcha');
    if (rc) {{ r.type = 'recaptchav2'; r.sitekey = rc.dataset.sitekey; }}
  }}
  if (!r.type && document.querySelector('script[src*="recaptcha"]')) {{
    const el = document.querySelector('[data-sitekey]');
    if (el) {{ r.type = 'recaptchav2'; r.sitekey = el.dataset.sitekey; }}
  }}
  if (!r.type) {{
    const fc = document.querySelector('#FunCaptcha, [data-pkey], .funcaptcha');
    if (fc) {{ r.type = 'funcaptcha'; r.sitekey = fc.dataset.pkey; }}
  }}
  if (!r.type && document.querySelector('script[src*="arkoselabs"], script[src*="funcaptcha"]')) {{
    const el = document.querySelector('[data-pkey]');
    if (el) {{ r.type = 'funcaptcha'; r.sitekey = el.dataset.pkey; }}
  }}
  if (r.type) {{ r.url = url; return r; }}
  return null;
}}"""

CAPTCHA_CREATE_TASK_JS = r"""async () => {{
  const r = await fetch('https://api.capsolver.com/createTask', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{
      clientKey: '{client_key}',
      task: {{
        type: 'TASK_TYPE',
        websiteURL: 'PAGE_URL',
        websiteKey: 'SITE_KEY'
      }}
    }})
  }});
  return await r.json();
}}"""

CAPTCHA_POLL_JS = r"""async () => {{
  const r = await fetch('https://api.capsolver.com/getTaskResult', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{
      clientKey: '{client_key}',
      taskId: 'TASK_ID'
    }})
  }});
  return await r.json();
}}"""

CAPTCHA_INJECT_RECAPTCHA_JS = r"""() => {{
  const token = 'THE_TOKEN';
  document.querySelectorAll('[name="g-recaptcha-response"]').forEach(el => {{ el.value = token; el.style.display = 'block'; }});
  if (window.___grecaptcha_cfg) {{
    const clients = window.___grecaptcha_cfg.clients;
    for (const key in clients) {{
      const walk = (obj, d) => {{
        if (d > 4 || !obj) return;
        for (const k in obj) {{
          if (typeof obj[k] === 'function' && k.length < 3) try {{ obj[k](token); }} catch(e) {{}}
          else if (typeof obj[k] === 'object') walk(obj[k], d+1);
        }}
      }};
      walk(clients[key], 0);
    }}
  }}
  return 'injected';
}}"""

CAPTCHA_INJECT_HCAPTCHA_JS = r"""() => {{
  const token = 'THE_TOKEN';
  const ta = document.querySelector('[name="h-captcha-response"], textarea[name*="hcaptcha"]');
  if (ta) ta.value = token;
  document.querySelectorAll('iframe[data-hcaptcha-response]').forEach(f => f.setAttribute('data-hcaptcha-response', token));
  const cb = document.querySelector('[data-hcaptcha-widget-id]');
  if (cb && window.hcaptcha) try {{ window.hcaptcha.getResponse(cb.dataset.hcaptchaWidgetId); }} catch(e) {{}}
  return 'injected';
}}"""

CAPTCHA_INJECT_TURNSTILE_JS = r"""() => {{
  const token = 'THE_TOKEN';
  const inp = document.querySelector('[name="cf-turnstile-response"], input[name*="turnstile"]');
  if (inp) inp.value = token;
  if (window.turnstile) try {{ const w = document.querySelector('.cf-turnstile'); if (w) window.turnstile.getResponse(w); }} catch(e) {{}}
  return 'injected';
}}"""

CAPTCHA_INJECT_FUNCAPTCHA_JS = r"""() => {{
  const token = 'THE_TOKEN';
  const inp = document.querySelector('#FunCaptcha-Token, input[name="fc-token"]');
  if (inp) inp.value = token;
  if (window.ArkoseEnforcement) try {{ window.ArkoseEnforcement.setConfig({{data: {{blob: token}}}}) }} catch(e) {{}}
  return 'injected';
}}"""

FORM_VERIFY_JS = r"""() => ({
  const visible = (el) => {
    if (!el || el.disabled) return false;
    const s = window.getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    if (el.getBoundingClientRect().width === 0) return false;
    return true;
  };
  const fields = [];
  document.querySelectorAll('input, select, textarea').forEach((el) => {
    if (!visible(el) && el.type !== 'hidden') return;
    const label = (
      el.labels?.[0]?.innerText ||
      el.getAttribute('aria-label') ||
      el.getAttribute('placeholder') ||
      el.name ||
      el.id ||
      el.type ||
      'field'
    ).trim().slice(0, 100);
    let value = '';
    if (el.type === 'checkbox' || el.type === 'radio') {
      value = el.checked ? 'checked' : 'unchecked';
    } else if (el.tagName === 'SELECT') {
      value = el.options[el.selectedIndex]?.text?.trim() || el.value;
    } else {
      value = (el.value || '').slice(0, 120);
    }
    const empty = el.type !== 'checkbox' && el.type !== 'radio' && !String(el.value || '').trim();
    fields.push({ label, tag: el.tagName.toLowerCase(), type: el.type || '', value, empty });
  });
  const errors = [...document.querySelectorAll('[role="alert"], [class*="error"], [class*="invalid"]')]
    .map((e) => (e.innerText || '').trim())
    .filter((t) => t.length > 2 && t.length < 200)
    .slice(0, 8);
  const buttons = [...document.querySelectorAll('button, [role="button"], input[type="submit"]')]
    .filter(visible)
    .map((b) => (b.innerText || b.value || '').trim())
    .filter(Boolean)
    .slice(0, 12);
  const disabledButtons = [...document.querySelectorAll('button, [role="button"], input[type="submit"]')]
    .filter((b) => b.disabled || b.getAttribute('aria-disabled') === 'true')
    .map((b) => (b.innerText || b.value || b.getAttribute('aria-label') || '').trim())
    .filter(Boolean)
    .slice(0, 12);
  const invalidFields = fields
    .filter((f) => /invalid|error|required/i.test(`${f.label} ${f.value}`))
    .slice(0, 12);
  const dateWidgets = [...document.querySelectorAll('[aria-label*="Month"], [aria-label*="Year"], input[placeholder*="MM"], input[placeholder*="YYYY"], select[name*="month"], select[name*="year"]')]
    .filter((el) => visible(el) || el.type === 'hidden')
    .map((el) => ({
      label: (el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.name || el.id || '').trim(),
      value: (el.value || '').slice(0, 40)
    }))
    .slice(0, 20);
  return {
    url: location.href,
    title: document.title.slice(0, 120),
    bodyText: (document.body?.innerText || '').slice(0, 4000),
    fieldCount: fields.length,
    emptyRequired: fields.filter((f) => f.empty).length,
    fields: fields.slice(0, 45),
    invalidFields,
    dateWidgets,
    visibleErrors: errors,
    visibleButtons: buttons,
    disabledButtons,
  };
})"""


def format_captcha_create_task(client_key: str) -> str:
    return CAPTCHA_CREATE_TASK_JS.format(client_key=client_key)


def format_captcha_poll(client_key: str) -> str:
    return CAPTCHA_POLL_JS.format(client_key=client_key)
