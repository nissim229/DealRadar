"""
photo_carousel.py
A self-contained HTML/CSS/JS photo carousel with real sliding transitions,
dot navigation, and price/badge overlays - embedded via
streamlit.components.v1.html.

This exists specifically because layering real Streamlit buttons on top of
st.image (for dots, a save-heart, etc.) was attempted multiple times and
confirmed unreliable in this environment - Streamlit's native image widget
doesn't give predictable control over its own stacking/click behavior.
Rendering the whole photo area as one custom HTML document sidesteps that
entirely: there's no st.image involved at all, so there's nothing to fight
for click priority. All interactivity here (dots, arrows) is plain JS
inside our own iframe.
"""


def render_photo_carousel_html(image_urls, price_label="", badge_html="", height=240, slide_labels=None):
    """Builds the carousel. image_urls: list of image URLs (can be empty -
    falls back to a placeholder). price_label: plain text like '$450,000'.
    badge_html: pre-rendered badge markup (from underwriting.render_deal_badge).
    Both are optional - pass "" to omit them (used for the plain photo-tour
    carousel in the details dialog, where a price/grade badge would just
    duplicate what's already shown above it).
    slide_labels: optional list of per-slide caption strings (e.g. compass
    directions), same length as image_urls - each rides along with its own
    slide instead of staying fixed like price_label/badge_html do."""

    if not image_urls:
        return f"""
        <div style="width:100%; height:{height}px; border-radius:10px;
                    background:linear-gradient(135deg,#2563eb,#1d4ed8); display:flex;
                    align-items:center; justify-content:center; font-size:48px; position:relative;">
            🏠
            <div style="position:absolute; top:10px; left:10px;">{badge_html}</div>
            <div style="position:absolute; bottom:12px; left:12px; background:rgba(15,23,42,0.78);
                        color:white; padding:6px 14px; border-radius:8px; font-weight:800;
                        font-size:20px; font-family:'Inter',-apple-system,sans-serif;">{price_label}</div>
        </div>
        """

    count = len(image_urls)

    def _slide(i, url):
        label = slide_labels[i] if slide_labels and i < len(slide_labels) else None
        label_html = f'<div class="dr-slide-label">{label}</div>' if label else ""
        return f'<div class="dr-slide"><img src="{url}" loading="lazy">{label_html}</div>'

    slides_html = "".join(_slide(i, url) for i, url in enumerate(image_urls))
    dots_html = "".join(
        f'<div class="dr-dot{" active" if i == 0 else ""}" data-index="{i}"></div>' for i in range(count)
    )
    nav_html = ""
    if count > 1:
        nav_html = (
            '<button class="dr-nav dr-nav-prev" id="dr-prev" aria-label="Previous photo">&#8249;</button>'
            '<button class="dr-nav dr-nav-next" id="dr-next" aria-label="Next photo">&#8250;</button>'
        )
    dots_wrap = f'<div class="dr-dots" id="dr-dots">{dots_html}</div>' if count > 1 else ""

    return f"""
    <div class="dr-carousel">
    <style>
        .dr-carousel {{
            position: relative; width: 100%; height: {height}px;
            border-radius: 10px; overflow: hidden; background: #1e293b;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        }}
        .dr-track {{
            display: flex; width: {count * 100}%; height: 100%;
            transition: transform 0.4s cubic-bezier(0.4, 0, 0.2, 1);
        }}
        .dr-slide {{ position: relative; width: {100 / count}%; height: 100%; flex-shrink: 0; }}
        .dr-slide img {{ width: 100%; height: 100%; object-fit: cover; display: block; pointer-events: none; -webkit-user-drag: none; }}
        .dr-slide-label {{
            position: absolute; bottom: 12px; left: 12px; z-index: 2;
            background: rgba(15,23,42,0.72); color: white; padding: 4px 11px;
            border-radius: 7px; font-weight: 700; font-size: 12.5px; letter-spacing: 0.2px;
        }}
        .dr-track {{ cursor: grab; touch-action: pan-y; }}
        .dr-track.dr-dragging {{ cursor: grabbing; }}
        .dr-badge {{ position: absolute; top: 10px; left: 10px; z-index: 2; }}
        .dr-price {{
            position: absolute; bottom: 12px; left: 12px; z-index: 2;
            background: rgba(15,23,42,0.78); color: white; padding: 6px 14px;
            border-radius: 8px; font-weight: 800; font-size: 20px;
        }}
        .dr-dots {{
            position: absolute; bottom: 8px; left: 50%; transform: translateX(-50%);
            z-index: 2; display: flex; gap: 6px;
            background: rgba(15,23,42,0.4); padding: 5px 8px; border-radius: 20px;
        }}
        .dr-dot {{
            width: 6px; height: 6px; border-radius: 50%;
            background: rgba(255,255,255,0.5); cursor: pointer;
            transition: background 0.2s, transform 0.2s;
        }}
        .dr-dot.active {{ background: white; transform: scale(1.35); }}
        .dr-nav {{
            position: absolute; top: 50%; transform: translateY(-50%);
            background: rgba(15,23,42,0.45); color: white; border: none;
            width: 28px; height: 28px; border-radius: 50%; cursor: pointer;
            font-size: 16px; z-index: 2; display: flex; align-items: center;
            justify-content: center; opacity: 0; transition: opacity 0.2s, background 0.2s;
        }}
        .dr-carousel:hover .dr-nav {{ opacity: 1; }}
        .dr-nav:hover {{ background: rgba(15,23,42,0.7); }}
        .dr-nav-prev {{ left: 8px; }}
        .dr-nav-next {{ right: 8px; }}
    </style>
    <div class="dr-track" id="dr-track">{slides_html}</div>
    <div class="dr-badge">{badge_html}</div>
    <div class="dr-price">{price_label}</div>
    {dots_wrap}
    {nav_html}
    </div>
    <script>
    (function() {{
        const carousel = document.querySelector('.dr-carousel');
        const track = document.getElementById('dr-track');
        const dots = document.querySelectorAll('.dr-dot');
        const total = {count};
        let current = 0;

        function setTransform(percent, animated) {{
            track.style.transition = animated ? '' : 'none';
            track.style.transform = 'translateX(-' + percent + '%)';
        }}

        function goTo(i) {{
            current = (i + total) % total;
            setTransform(current * (100 / total), true);
            dots.forEach((d, idx) => d.classList.toggle('active', idx === current));
        }}

        dots.forEach(d => d.addEventListener('click', () => goTo(parseInt(d.dataset.index))));

        const prevBtn = document.getElementById('dr-prev');
        const nextBtn = document.getElementById('dr-next');
        if (prevBtn) prevBtn.addEventListener('click', () => goTo(current - 1));
        if (nextBtn) nextBtn.addEventListener('click', () => goTo(current + 1));

        // Drag / swipe support - pointer events cover mouse, touch, and pen
        // in one API. The track follows the pointer 1:1 while dragging (no
        // transition), then snaps to the nearest slide on release based on
        // a distance threshold, matching typical native swipe feel.
        let dragging = false;
        let startX = 0;
        let deltaPercent = 0;
        let carouselWidth = 1;

        track.addEventListener('pointerdown', (e) => {{
            if (total <= 1) return;
            dragging = true;
            startX = e.clientX;
            deltaPercent = 0;
            carouselWidth = carousel.getBoundingClientRect().width || 1;
            track.classList.add('dr-dragging');
            track.setPointerCapture(e.pointerId);
        }});

        track.addEventListener('pointermove', (e) => {{
            if (!dragging) return;
            const deltaPx = e.clientX - startX;
            deltaPercent = (deltaPx / carouselWidth) * (100 / total);
            setTransform(current * (100 / total) - deltaPercent, false);
        }});

        function endDrag() {{
            if (!dragging) return;
            dragging = false;
            track.classList.remove('dr-dragging');
            const draggedFraction = deltaPercent / (100 / total);
            if (draggedFraction > 0.18) {{
                goTo(current - 1);
            }} else if (draggedFraction < -0.18) {{
                goTo(current + 1);
            }} else {{
                goTo(current);
            }}
        }}

        track.addEventListener('pointerup', endDrag);
        track.addEventListener('pointercancel', endDrag);
        track.addEventListener('pointerleave', () => {{ if (dragging) endDrag(); }});
    }})();
    </script>
    """