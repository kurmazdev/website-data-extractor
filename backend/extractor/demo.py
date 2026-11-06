"""Owned, deterministic fixtures. No network or loopback exception is needed."""

import json
from urllib.parse import parse_qs, urlencode, urlsplit

BOOKS = [
    ("The Creative Act", "Rick Rubin", "$24.00", "Creativity"),
    ("A Field Guide to Getting Lost", "Rebecca Solnit", "$18.00", "Essays"),
    ("The Design of Everyday Things", "Don Norman", "$22.50", "Design"),
    ("Braiding Sweetgrass", "Robin Wall Kimmerer", "$20.00", "Nature"),
    ("Ways of Seeing", "John Berger", "$16.00", "Art"),
    ("The Art of Noticing", "Rob Walker", "$19.00", "Creativity"),
    ("On Writing Well", "William Zinsser", "$17.50", "Writing"),
    ("The Shape of Design", "Frank Chimero", "$21.00", "Design"),
    ("A Pattern Language", "Christopher Alexander", "$45.00", "Architecture"),
    ("The Living Mountain", "Nan Shepherd", "$15.00", "Nature"),
    ("Invisible Cities", "Italo Calvino", "$14.00", "Fiction"),
]


def fixture(url):
    p = urlsplit(url)
    if p.path == "/robots.txt":
        return 200, "text/plain", b"User-agent: *\nAllow: /\nDisallow: /restricted\n"
    if p.path == "/malformed":
        return 200, "text/html", b"<main><article class=book><h2>Unclosed title"
    if p.path != "/catalog":
        return 404, "text/plain", b"Fixture not found"
    query = parse_qs(p.query)
    try:
        page = int(query.get("page", ["1"])[0])
    except ValueError:
        return 400, "text/plain", b"Invalid demo page number"

    if page not in (1, 2, 3) or (page == 3 and query.get("failure") == ["1"]):
        return 503, "text/plain", b"Demo page temporarily unavailable"
    items = BOOKS[(page - 1) * 4 : page * 4]
    if page == 2:
        items = [BOOKS[3]] + items  # deliberate duplicate across pages
    rows = "".join(
        f'<article class="book"><h2>{title}</h2><p class="author">{author}</p>'
        f"{'' if title == 'The Shape of Design' else f'<span class=price>{price}</span>'}"
        f'<span class="category">{category}</span></article>'
        for title, author, price, category in items
    )
    next_query = {"page": str(page + 1)}
    for flag in ("failure", "js"):
        if query.get(flag) == ["1"] or (flag == "js" and query.get(flag) == ["slow"]):
            next_query[flag] = query[flag][0]
    link = (
        f'<a class="next" href="?{urlencode(next_query)}">Next</a>' if page < 3 else ""
    )
    if query.get("js") in (["1"], ["slow"]):
        wait_ms = 3000 if query.get("js") == ["slow"] else 100
        html = f'<main id="catalog"></main><script>setTimeout(() => {{document.querySelector("main").innerHTML = {json.dumps(rows + link)}; }}, {wait_ms})</script>'
    else:
        html = f"<main>{rows}{link}</main>"
    return (
        200,
        "text/html",
        (
            "<!doctype html><html><head><title>Demo bookshop</title></head><body>"
            + html
            + "</body></html>"
        ).encode(),
    )
