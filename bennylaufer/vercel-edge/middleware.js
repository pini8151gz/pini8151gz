// Serves the static site straight from the GitHub repo (pinned commit) without a Git connection.
// HTML is fetched here and returned as text/html; everything else is rewritten to jsDelivr in vercel.json.
const SHA = '8d2b9453efa06b110799da7db7529743f59f6006';
const SOURCES = [
  'https://cdn.jsdelivr.net/gh/pini8151gz/pini8151gz@' + SHA + '/bennylaufer/site/',
  'https://raw.githubusercontent.com/pini8151gz/pini8151gz/' + SHA + '/bennylaufer/site/',
];

export const config = { matcher: ['/', '/en', '/en/', '/fr', '/fr/'] };

export default async function middleware(request) {
  const url = new URL(request.url);
  const lang = url.pathname.replace(/\//g, '');
  if (lang && !url.pathname.endsWith('/')) return Response.redirect(new URL('/' + lang + '/', url), 308);
  const file = lang ? lang + '/index.html' : 'index.html';
  let html = null;
  for (const base of SOURCES) {
    try {
      const r = await fetch(base + file);
      if (r.ok) { html = await r.text(); break; }
    } catch (e) { /* try the next source */ }
  }
  if (!html) return new Response('Temporarily unavailable', { status: 503 });
  html = html.split('https://bennylaufer.com/og.jpg').join(url.origin + '/og.jpg');
  const headers = {
    'content-type': 'text/html; charset=utf-8',
    'cache-control': 'public, max-age=0, must-revalidate',
    'x-content-type-options': 'nosniff',
    'referrer-policy': 'strict-origin-when-cross-origin',
    'x-frame-options': 'DENY',
    'content-security-policy': "frame-ancestors 'none'",
    'permissions-policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()',
    'cross-origin-opener-policy': 'same-origin',
  };
  // the real home is bennylaufer.com (canonical); keep this preview host out of search results
  if (url.hostname.endsWith('.vercel.app')) headers['x-robots-tag'] = 'noindex';
  return new Response(html, { headers });
}
