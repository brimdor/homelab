#!/bin/sh
# gen-index.sh — Regenerates index.html from HTML files with PAGES_META comments
# POSIX-compliant for Alpine /bin/sh (ash)
# Run: kubectl exec -n pages deploy/pages -- /usr/local/bin/gen-index.sh

HTML_DIR="/usr/share/nginx/html"
INDEX="$HTML_DIR/index.html"

# Collect pages with metadata into a temp file
TMPFILE=$(mktemp)
for f in "$HTML_DIR"/*.html; do
  fname=$(basename "$f")
  [ "$fname" = "index.html" ] && continue
  [ ! -f "$f" ] && continue

  # Extract PAGES_META from first 5 lines
  meta=$(head -5 "$f" | sed -n 's/.*PAGES_META: \({.*}\).*/\1/p' | head -1)
  if [ -n "$meta" ]; then
    title=$(printf '%s' "$meta" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('title','Untitled'))" 2>/dev/null || echo "Untitled")
    date=$(printf '%s' "$meta" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('date','Unknown'))" 2>/dev/null || echo "Unknown")
    desc=$(printf '%s' "$meta" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('description','')[:120])" 2>/dev/null || echo "")
    tags=$(printf '%s' "$meta" | python3 -c "import sys,json; print(' '.join(json.loads(sys.stdin.read()).get('tags',[])))" 2>/dev/null || echo "")
    printf '%s|%s|%s|%s|%s\n' "$date" "$title" "$desc" "$tags" "$fname" >> "$TMPFILE"
  fi
done

# Sort by date descending
sorted=$(sort -t'|' -k1 -r "$TMPFILE")
rm -f "$TMPFILE"

# Extract the latest date (first entry after sort = most recent)
latest_date=""
if [ -n "$sorted" ]; then
  latest_date=$(printf '%s\n' "$sorted" | head -1 | cut -d'|' -f1)
fi
[ -z "$latest_date" ] && latest_date="No pages yet"

# Build tag HTML
build_tags() {
  _tags="$1"
  _html=""
  for _tag in $_tags; do
    [ -n "$_tag" ] && _html="${_html}<span class=\"tag\">${_tag}</span>"
  done
  printf '%s' "$_html"
}

# Write index.html
cat > "$INDEX" << 'HEADER'
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Pages</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--glass-bg:rgba(255,140,0,0.06);--glass-border:rgba(255,140,0,0.15);--glass-radius:20px;--content-bg:rgba(20,15,8,0.85);--text-primary:#f0ece4;--text-secondary:#b0a890;--accent:#ff8c00;--accent-light:#ffa940}
@media(max-width:768px){:root{--glass-radius:16px}}
body{background:linear-gradient(135deg,#0d0d0d 0%,#1a1008 30%,#1a0f05 60%,#0a0a0a 100%);background-attachment:fixed;min-height:100vh;font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display','Segoe UI',system-ui,sans-serif;color:var(--text-primary);line-height:1.6;padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)}
.glass{background:var(--glass-bg);backdrop-filter:blur(20px) saturate(160%);-webkit-backdrop-filter:blur(20px) saturate(160%);border-radius:var(--glass-radius);border:1px solid var(--glass-border);box-shadow:0 8px 32px rgba(0,0,0,0.4),inset 0 1px 0 rgba(255,140,0,0.08)}

nav{position:sticky;top:0;z-index:100;padding:1rem 1.5rem;display:flex;align-items:center;margin:1rem}
nav h1{font-size:1.25rem;font-weight:700;color:var(--accent)}
main{max-width:1200px;margin:0 auto;padding:1rem}
.hero{padding:2rem 1rem;text-align:center}
.hero h2{font-size:clamp(1.5rem,4vw,2.5rem);font-weight:700;margin-bottom:0.5rem;background:linear-gradient(135deg,var(--accent),#1a1a1a);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.hero p{color:var(--text-secondary);font-size:clamp(0.9rem,2vw,1.1rem)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,320px),1fr));gap:1.25rem;margin-top:2rem}
.card{background:var(--content-bg);border-radius:16px;border:1px solid rgba(255,140,0,0.1);padding:1.5rem;text-decoration:none;color:var(--text-primary);transition:transform 0.2s,border-color 0.2s;display:block}
.card:hover{transform:translateY(-2px);border-color:rgba(255,140,0,0.35)}
.card-title{font-size:1.15rem;font-weight:600;margin-bottom:0.4rem}
.card-date{font-size:0.8rem;color:var(--text-secondary);margin-bottom:0.5rem}
.card-desc{font-size:0.9rem;color:var(--text-secondary);line-height:1.5}
.card-tags{margin-top:0.75rem;display:flex;flex-wrap:wrap;gap:0.4rem}
.tag{background:rgba(255,140,0,0.15);color:var(--accent-light);padding:0.2rem 0.6rem;border-radius:999px;font-size:0.75rem}
footer{padding:2.5rem 1.5rem 2rem;text-align:center;border-top:1px solid rgba(255,140,0,0.08);margin-top:2rem}.footer-name{font-size:1rem;font-weight:700;color:var(--text-primary);margin-bottom:0.35rem}.footer-updated{font-size:0.8rem;color:var(--accent-light);margin-bottom:0.5rem}.footer-tagline{font-size:0.75rem;color:var(--text-secondary);letter-spacing:0.03em}
.empty-state{text-align:center;padding:4rem 1rem;color:var(--text-secondary)}
.empty-state p{font-size:1.1rem;margin-top:0.5rem}
@media(prefers-reduced-transparency){.glass{background:rgba(20,16,8,0.95);backdrop-filter:none;-webkit-backdrop-filter:none}.glass::before{display:none}}
@media(prefers-reduced-motion:reduce){*{transition-duration:0.01ms!important;animation-duration:0.01ms!important}}
a,button,[role="button"]{min-height:44px;min-width:44px;display:inline-flex;align-items:center}
</style>
</head>
<body>
<nav class="glass"><h1>Pages</h1></nav>
<main>
<div class="hero"><h2>The Collection</h2><p>A living library of visualizations, diagrams, and documents</p></div>
<div class="grid">
HEADER

# Add each page as a card
count=0
if [ -n "$sorted" ]; then
  printf '%s\n' "$sorted" | while IFS='|' read -r date title desc tags fname; do
    [ -z "$fname" ] && continue
    tag_html=$(build_tags "$tags")
    printf '<a class="card" href="%s">\n  <div class="card-title">%s</div>\n  <div class="card-date">%s</div>\n  <div class="card-desc">%s</div>\n  <div class="card-tags">%s</div>\n</a>\n' "$fname" "$title" "$date" "$desc" "$tag_html" >> "$INDEX"
    count=$((count + 1))
  done
fi

# If no pages, show empty state
if [ ! -s "$INDEX" ] || ! grep -q 'card-title' "$INDEX"; then
  cat >> "$INDEX" << 'EMPTY'
<div class="empty-state">
  <h2>No pages yet</h2>
  <p>Pages will appear here as they are published.</p>
</div>
EMPTY
fi

cat >> "$INDEX" << FOOTER
</div>
</main>
<footer>
  <div class="footer-name">Pages</div>
  <div class="footer-updated">Last updated: ${latest_date}</div>
  <div class="footer-tagline">Auto-indexed collection</div>
</footer>
</body>
</html>
FOOTER

echo "Index regenerated"