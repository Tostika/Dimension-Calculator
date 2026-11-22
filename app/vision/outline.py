"""Finding an item's outline, ported from the team's measure.py (the A4-sheet script that
measured a bank card at 85.5-86.1 mm).

1. The camera picture is warped into a straight top view of the base, 4 px per mm
   (lens distortion removed in the same step).
2. How the EMPTY paper would look at every spot is estimated from the picture itself
   (a smooth surface fitted to the paper, plus local corrections), so uneven light from a
   window or a lamp does not shift edges.
3. Every pixel gets an 'object' score: darker, brighter or a different colour than the paper.
4. Every outline point is then moved to where the item REALLY ends: the steepest drop of
   that score across the edge, with sub-pixel precision. A soft shadow or a glow around
   the item is not taken as part of it.
"""
import cv2
import numpy as np

PX_PER_MM = 4
EDGE_MARGIN_MM = 4          # strip along the border of the top view that is ignored
MIN_AREA_MM2 = 60           # smaller blobs are ignored (dust, text)
DARK_RATIO = 0.72           # darker than 72 % of the paper = object
BRIGHT_RATIO = 1.06         # 6 % brighter than the paper = object (white plastic)
CHROMA_THR = 10             # colour difference from the paper = object
GAP_MM = 5                  # pieces closer than this are one item
MARKER_MARGIN_MM = 4        # around each base marker, left out of everything


class NoItem(Exception):
    pass


# ---------------------------------------------------------------- top view

def top_view(frame, base_map, centers_mm, marker_size_mm):
    """Straight top view of the area between the base markers. Returns
    (image, (x0, y0) in base mm of its top-left pixel, mask of the usable area)."""
    cs = np.array([c for c in centers_mm.values()], np.float64)
    x0, y0 = cs[:, 0].min(), cs[:, 1].min()
    W = int(round((cs[:, 0].max() - x0) * PX_PER_MM))
    H = int(round((cs[:, 1].max() - y0) * PX_PER_MM))
    u, v = np.meshgrid(np.arange(W, dtype=np.float64), np.arange(H, dtype=np.float64))
    mm = np.stack([x0 + u.ravel() / PX_PER_MM, y0 + v.ravel() / PX_PER_MM], 1)
    px = mm_to_camera_px(mm, base_map).reshape(H, W, 2).astype(np.float32)
    top = cv2.remap(frame, px[..., 0], px[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    usable = np.full((H, W), 255, np.uint8)
    half = marker_size_mm / 2.0 + MARKER_MARGIN_MM
    for c in cs:
        a = ((c - [x0, y0] - half) * PX_PER_MM).astype(int)
        b = ((c - [x0, y0] + half) * PX_PER_MM).astype(int)
        cv2.rectangle(usable, tuple(a), tuple(b), 0, -1)
    return top, (float(x0), float(y0)), usable


def mm_to_camera_px(mm, base_map):
    """Base mm -> real (distorted) camera pixels."""
    und = cv2.perspectiveTransform(np.asarray(mm, np.float64).reshape(-1, 1, 2), base_map.H_inv).reshape(-1, 2)
    calib = base_map.calib
    if not calib:
        return und
    K = np.asarray(calib["K"], np.float64)
    dist = np.asarray(calib["dist"], np.float64)
    xn = (und[:, 0] - K[0, 2]) / K[0, 0]
    yn = (und[:, 1] - K[1, 2]) / K[1, 1]
    obj = np.stack([xn, yn, np.ones_like(xn)], 1).reshape(-1, 1, 3)
    out, _ = cv2.projectPoints(obj, np.zeros(3), np.zeros(3), K, dist)
    return out.reshape(-1, 2)


def to_lab(img):
    return cv2.cvtColor(cv2.GaussianBlur(img, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)


# ---------------------------------------------------------------- paper and score

def score(lab, ref):
    """Object score per pixel: >= 1 means 'object'. Darker than the paper, brighter
    than the paper, or a different colour. A soft shadow is only slightly darker."""
    ratio = lab[..., 0] / np.maximum(ref[..., 0], 1.0)
    da = lab[..., 1] - ref[..., 1]
    db = lab[..., 2] - ref[..., 2]
    dark = np.clip(1.0 - ratio, 0, None) / (1.0 - DARK_RATIO)
    bright = np.clip(ratio - 1.0, 0, None) / (BRIGHT_RATIO - 1.0)
    col = np.hypot(da, db) / CHROMA_THR
    return np.maximum(np.maximum(dark, col), bright)


def paper_model(lab, usable):
    """How the EMPTY paper would look at every spot, estimated from the live picture:
    a smooth surface fitted to the pixels that look like paper, then small local
    corrections from the paper right next to each spot. Under an item the paper is
    filled in from the paper around it. Items have SHARP edges, light changes softly."""
    q = 1.0 / PX_PER_MM
    sm = cv2.resize(lab, None, fx=q, fy=q, interpolation=cv2.INTER_AREA)
    h, w = sm.shape[:2]
    v, u = np.mgrid[0:h, 0:w].astype(np.float32)
    u = u / max(w - 1, 1) * 2 - 1
    v = v / max(h - 1, 1) * 2 - 1
    A = np.stack([np.ones_like(u), u, v, u * u, u * v, v * v,
                  u ** 3, u * u * v, u * v * v, v ** 3], -1).reshape(-1, 10)
    inner = cv2.resize(usable, (w, h), interpolation=cv2.INTER_NEAREST) > 0
    e = EDGE_MARGIN_MM + 2
    inner[:e, :] = False; inner[-e:, :] = False; inner[:, :e] = False; inner[:, -e:] = False
    L, a, b = sm[..., 0], sm[..., 1], sm[..., 2]
    Y = sm.reshape(-1, 3)
    mL = max(float(np.median(L[inner])), 1.0)
    ma, mb = float(np.median(a[inner])), float(np.median(b[inner]))
    paper = inner & (np.abs(L / mL - 1) < 0.15) & (np.hypot(a - ma, b - mb) < 8)
    fit = np.empty_like(sm)
    fit[...] = (mL, ma, mb)
    sub = np.zeros((h, w), bool)
    sub[::2, ::2] = True
    for tol in (0.10, 0.07, 0.05, 0.05):
        idx = (paper & sub).ravel()
        if idx.sum() < 400:
            break
        coef = np.linalg.lstsq(A[idx], Y[idx], rcond=None)[0]
        fit = (A @ coef).reshape(h, w, 3).astype(np.float32)
        r = L / np.maximum(fit[..., 0], 1.0)
        paper = inner & (np.abs(r - 1) < tol) & (np.hypot(a - fit[..., 1], b - fit[..., 2]) < 6)
    sc = score(sm, fit)
    cand = cv2.morphologyEx((sc >= 0.5).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    rel = L / np.maximum(fit[..., 0], 1.0)
    g = lambda ch: cv2.magnitude(cv2.Sobel(ch, cv2.CV_32F, 1, 0, ksize=3),
                                 cv2.Sobel(ch, cv2.CV_32F, 0, 1, ksize=3)) / 8.0
    edge = (g(rel) > 0.03) | (np.hypot(g(a), g(b)) > 3.0)
    loops = cv2.morphologyEx(edge.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    lc, _ = cv2.findContours(loops, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    enclosed = np.zeros_like(loops)
    cv2.drawContours(enclosed, lc, -1, 1, -1)
    items = np.zeros_like(cand)
    n, lab_c, stats, _ = cv2.connectedComponentsWithStats(cand)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < 20:
            continue
        x, y, ww, hh = stats[i, :4]
        x0, y0, x1, y1 = max(x - 4, 0), max(y - 4, 0), min(x + ww + 4, w), min(y + hh + 4, h)
        cm = (lab_c[y0:y1, x0:x1] == i).astype(np.uint8)
        near = cv2.dilate(cm, np.ones((5, 5), np.uint8)) > 0
        if not edge[y0:y1, x0:x1][near].any():
            continue                                      # no sharp edge at all: light
        enc = (enclosed[y0:y1, x0:x1] > 0) & near
        if enc.sum() >= 0.5 * cm.sum():
            items[y0:y1, x0:x1] |= enc.astype(np.uint8)
        else:
            cc, _ = cv2.findContours(cm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(items[y0:y1, x0:x1], cc, -1, 1, -1)
    items = cv2.dilate(items, np.ones((7, 7), np.uint8))
    wgt = (inner & (items == 0)).astype(np.float32)
    res = (sm - fit) * wgt[..., None]
    wb = cv2.GaussianBlur(wgt, (0, 0), 6.0)
    rb = cv2.GaussianBlur(res, (0, 0), 6.0)
    corr = rb / np.maximum(wb, 1e-3)[..., None] * np.clip(wb / 0.3, 0, 1)[..., None]
    model = fit + corr
    H, W = lab.shape[:2]
    return cv2.resize(model, (W, H), interpolation=cv2.INTER_LINEAR)


# ---------------------------------------------------------------- the item

def _clean(m):
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))


def find_item(top, usable):
    """The item on the base. Returns (outline in top-view px, float, Nx2; partial)."""
    lab = to_lab(top)
    ref = paper_model(lab, usable)
    sc = score(lab, ref)
    e = int(EDGE_MARGIN_MM * PX_PER_MM)
    sc[:e, :] = 0; sc[-e:, :] = 0; sc[:, :e] = 0; sc[:, -e:] = 0
    sc[usable == 0] = 0
    L8 = cv2.cvtColor(top, cv2.COLOR_BGR2LAB)[:, :, 0]
    tex = cv2.GaussianBlur(cv2.absdiff(L8, cv2.medianBlur(L8, 3)).astype(np.float32), (0, 0), 1.5)

    coarse = _clean((sc >= 0.7).astype(np.uint8) * 255)
    cnts, _ = cv2.findContours(coarse, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    H, W = sc.shape
    pad = 8 * PX_PER_MM
    k1 = np.ones((2 * PX_PER_MM + 1,) * 2, np.uint8)
    k3 = np.ones((6 * PX_PER_MM + 1,) * 2, np.uint8)
    s1 = cv2.GaussianBlur(sc, (0, 0), PX_PER_MM)
    far = cv2.dilate(coarse[::4, ::4], np.ones((5, 5), np.uint8)) == 0
    far &= usable[::4, ::4] > 0
    bm = (EDGE_MARGIN_MM + 6) * PX_PER_MM // 4
    far[:bm, :] = False; far[-bm:, :] = False; far[:, :bm] = False; far[:, -bm:] = False
    bgpx = s1[::4, ::4][far]
    noise = float(np.percentile(bgpx, 99)) if bgpx.size else 0.15
    edge_img = cv2.GaussianBlur(sc, (0, 0), 1.0)
    tp = tex[::4, ::4][far]
    tex_thr = max(2.0, 1.2 * float(np.percentile(tp, 99.9))) if tp.size else 2.5
    marg = EDGE_MARGIN_MM * PX_PER_MM + 2
    dets = []
    for c in cnts:
        if cv2.contourArea(c) < MIN_AREA_MM2 * PX_PER_MM ** 2:
            continue
        x, y, w, h = cv2.boundingRect(c)
        partial = x <= marg or y <= marg or x + w >= W - marg or y + h >= H - marg
        x0, y0 = max(x - pad, 0), max(y - pad, 0)
        x1, y1 = min(x + w + pad, W), min(y + h + pad, H)
        roi = sc[y0:y1, x0:x1]
        inside = np.zeros(roi.shape, np.uint8)
        cv2.drawContours(inside, [c - [x0, y0]], -1, 255, -1)
        band = cv2.subtract(cv2.erode(inside, k1), cv2.erode(inside, k3))
        if not band.any():
            band = inside
        ring = cv2.subtract(cv2.dilate(inside, k3), cv2.dilate(inside, k1))
        if ring.any() and float(roi[band > 0].mean()) - float(roi[ring > 0].mean()) < 0.5:
            continue                                   # no sharp edge: uneven light, not an item
        level = np.percentile(roi[band > 0], 20)
        thr = max(1.0, level / 2.0)
        fine = _clean((roi >= thr).astype(np.uint8) * 255)
        fb = cv2.subtract(cv2.erode(fine, k1), cv2.erode(fine, k3))
        body = float(np.percentile(roi[fb > 0], 75)) if fb.any() else float(level)
        pale = body < 2.0
        if pale and fine.any():
            # a pale item (white-ish, looks like the paper): add its texture and rim lines
            tl = (tex[y0:y1, x0:x1] >= tex_thr).astype(np.uint8)
            _, lb = cv2.connectedComponents(tl)
            near = cv2.dilate(fine, np.ones((PX_PER_MM * 2 + 1,) * 2, np.uint8)) > 0
            keep = np.unique(lb[near & (tl > 0)])
            keep = keep[keep > 0]
            if keep.size:
                grown = cv2.bitwise_or(fine, np.isin(lb, keep).astype(np.uint8) * 255)
                grown = cv2.morphologyEx(grown, cv2.MORPH_CLOSE, np.ones((2 * PX_PER_MM + 1,) * 2, np.uint8))
                gc, _ = cv2.findContours(grown, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
                filled = np.zeros_like(grown)
                cv2.drawContours(filled, gc, -1, 255, -1)
                fine = cv2.bitwise_or(fine, filled)
        fc, _ = cv2.findContours(fine, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not fc:
            continue

        def overlap(cc):
            m_ = np.zeros(roi.shape, np.uint8)
            cv2.drawContours(m_, [cc], -1, 255, -1)
            return cv2.countNonZero(cv2.bitwise_and(m_, inside))
        c = max(fc, key=overlap) + [x0, y0]
        if cv2.contourArea(c) < MIN_AREA_MM2 * PX_PER_MM ** 2:
            continue
        c = _fill_bites(c, s1, noise)
        cf = _snap(c, edge_img, max(body, 0.8), max(0.25, 1.5 * noise),
                   inward_mm=2.0 if pale else 12.0, spike_mm=1.5 if pale else 0.4)
        dets.append(dict(cnt=np.round(cf).astype(np.int32), cntf=cf.reshape(-1, 2),
                         area=abs(cv2.contourArea(cf)), partial=partial))
    if not dets:
        raise NoItem()
    # pieces closer than GAP_MM belong to one item; the biggest group is the item
    canvas = np.zeros(sc.shape, np.uint8)
    for d in dets:
        cv2.drawContours(canvas, [d["cnt"]], -1, 255, -1)
    r = int(GAP_MM * PX_PER_MM / 2)
    _, lab_g = cv2.connectedComponents(cv2.dilate(canvas, np.ones((2 * r + 1,) * 2, np.uint8)))
    groups = {}
    for d in dets:
        x, y = d["cnt"][0][0]
        groups.setdefault(int(lab_g[y, x]), []).append(d)
    members = max(groups.values(), key=lambda g_: sum(m["area"] for m in g_))
    pts = np.vstack([m["cntf"] for m in members]).astype(np.float32)
    if len(members) == 1:
        outline = members[0]["cntf"]
    else:
        u = np.zeros(sc.shape, np.uint8)
        for m in members:
            cv2.drawContours(u, [m["cnt"]], -1, 255, -1)
        u = cv2.morphologyEx(u, cv2.MORPH_CLOSE, np.ones((2 * r + 1,) * 2, np.uint8))
        uc, _ = cv2.findContours(u, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        outline = max(uc, key=cv2.contourArea).reshape(-1, 2).astype(np.float32)
    return outline, pts, any(m["partial"] for m in members)


def _fill_bites(c, s1, noise):
    """A pale part of an item can be missed, leaving a 'bite' in the outline. It is filled
    when its inside is above the paper noise and a faint steady edge closes it off."""
    if len(c) < 10:
        return c
    try:
        hull = cv2.convexHull(c, returnPoints=False)
        defects = cv2.convexityDefects(c, hull)
    except cv2.error:
        return c
    if defects is None:
        return c
    pts = c.reshape(-1, 2)
    n = len(pts)
    H, W = s1.shape
    thr_in = max(0.25, 1.5 * noise)
    add = []
    for st_i, en_i, _, depth in defects.reshape(-1, 4):
        if depth / 256.0 < 1.5 * PX_PER_MM:
            continue
        idx = np.arange(st_i, en_i + 1) if en_i >= st_i else np.r_[st_i:n, 0:en_i + 1]
        poly = pts[idx]
        if len(poly) < 3 or cv2.contourArea(poly) < 20 * PX_PER_MM ** 2:
            continue
        a, b = pts[st_i].astype(np.float32), pts[en_i].astype(np.float32)
        Ln = float(np.linalg.norm(b - a))
        if Ln < 5 * PX_PER_MM:
            continue
        m = np.zeros((H, W), np.uint8)
        cv2.fillPoly(m, [poly], 1)
        m = cv2.erode(m, np.ones((PX_PER_MM + 1,) * 2, np.uint8))
        if m.sum() < 10 or float(s1[m > 0].mean()) < thr_in:
            continue
        u = (b - a) / Ln
        nv = np.array([u[1], -u[0]], np.float32)
        mid = (a + b) / 2
        probe = mid - nv * 2 * PX_PER_MM
        if 0 <= probe[0] < W and 0 <= probe[1] < H and m[int(probe[1]), int(probe[0])] == 0:
            nv = -nv
        ts = np.linspace(0.1, 0.9, 25)[:, None]
        line = a + (b - a) * ts
        pin = line - nv * PX_PER_MM
        pout = line + nv * 1.5 * PX_PER_MM
        ok = (pout[:, 0] >= 0) & (pout[:, 0] < W - 1) & (pout[:, 1] >= 0) & (pout[:, 1] < H - 1)
        if ok.sum() < 10:
            continue
        vi = cv2.remap(s1, pin[ok, 0:1].astype(np.float32), pin[ok, 1:2].astype(np.float32), cv2.INTER_LINEAR)
        vo = cv2.remap(s1, pout[ok, 0:1].astype(np.float32), pout[ok, 1:2].astype(np.float32), cv2.INTER_LINEAR)
        diff = (vi - vo).ravel()
        if np.median(diff) >= 0.15 and (diff > 0.08).mean() >= 0.7:
            add.append(poly)
    if not add:
        return c
    x, y, w, h = cv2.boundingRect(c)
    m = np.zeros((h + 2, w + 2), np.uint8)
    cv2.drawContours(m, [c - [x - 1, y - 1]], -1, 255, -1)
    for poly in add:
        cv2.fillPoly(m, [poly - [x - 1, y - 1]], 255)
    cc, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return max(cc, key=cv2.contourArea) + [x - 1, y - 1]


def _snap(cnt, img, level, faint, inward_mm=5.0, spike_mm=0.4):
    """Move every outline point to the item's REAL edge: along the line across the
    outline the edge is where the 'object' level drops fastest (sub-pixel)."""
    p = cnt.reshape(-1, 2).astype(np.float32)
    n = len(p)
    if n < 24:
        return p.reshape(-1, 1, 2)
    g = np.exp(-0.5 * (np.arange(-6, 7) / 2.0) ** 2)
    g /= g.sum()
    ps = np.stack([np.convolve(np.concatenate([p[-6:, i], p[:, i], p[:6, i]]), g, "valid")
                   for i in range(2)], 1)
    kk = int(1.5 * PX_PER_MM)
    t = np.roll(ps, -kk, 0) - np.roll(ps, kk, 0)
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-6)
    nrm = np.stack([t[:, 1], -t[:, 0]], 1).astype(np.float32)
    idx = np.linspace(0, n - 1, 24).astype(int)
    test = p[idx] + 2.0 * nrm[idx]
    inside = sum(cv2.pointPolygonTest(cnt, (float(a), float(b)), False) > 0 for a, b in test)
    if inside > len(idx) / 2:
        nrm = -nrm
    offs = np.arange(-inward_mm * PX_PER_MM, 1.5 * PX_PER_MM + 0.25, 0.5, dtype=np.float32)
    X = p[:, :1] + nrm[:, :1] * offs
    Y = p[:, 1:] + nrm[:, 1:] * offs
    prof = cv2.remap(img, X, Y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    raw = prof
    prof = np.clip(prof, 0, level) / level
    d = prof[:, :-2] - prof[:, 2:]
    z = int(np.argmin(np.abs(offs)))
    notpaper = prof >= faint / level
    run = np.ones(len(offs), bool)[None, :].repeat(n, 0)
    run[:, z + 1:] = np.cumprod(notpaper[:, z + 1:], axis=1).astype(bool)
    d = np.where(run[:, 1:-1], d, -1.0)
    mx = d.max(1, keepdims=True)
    cand = d >= np.maximum(0.4 * mx, 0.08)
    j = d.shape[1] - 1 - np.argmax(cand[:, ::-1], 1)
    for i in range(n):
        k_ = j[i]
        while k_ > 0 and cand[i, k_ - 1] and d[i, k_ - 1] >= d[i, k_]:
            k_ -= 1
        j[i] = k_
    best = d[np.arange(n), j]
    draw = raw[:, :-2] - raw[:, 2:]
    w = 3
    lo = np.clip(j - w, 0, d.shape[1] - 1)
    win = np.stack([draw[np.arange(n), np.clip(lo + q, 0, d.shape[1] - 1)] for q in range(2 * w + 1)], 1)
    j = np.clip(lo + np.argmax(win, 1), 0, d.shape[1] - 1)
    jj = np.clip(j, 1, d.shape[1] - 2)
    a, b, c3 = draw[np.arange(n), jj - 1], draw[np.arange(n), jj], draw[np.arange(n), jj + 1]
    den = a - 2 * b + c3
    sub = np.where(np.abs(den) > 1e-6, 0.5 * (a - c3) / np.where(np.abs(den) > 1e-6, den, 1), 0)
    shift = offs[j + 1] + np.clip(sub, -0.5, 0.5) * 0.5
    ok = (best >= 0.08) & (j > 0) & (j < d.shape[1] - 1)
    if ok.sum() < max(8, n // 10):
        return p.reshape(-1, 1, 2)
    idx = np.arange(n)
    shift = np.interp(idx, idx[ok], shift[ok], period=n).astype(np.float32)
    k = 2 * PX_PER_MM
    ext = np.concatenate([shift[-k:], shift, shift[:k]])
    med = np.median(np.lib.stride_tricks.sliding_window_view(ext, 2 * k + 1), axis=1)
    g = np.exp(-0.5 * (np.arange(-2 * PX_PER_MM, 2 * PX_PER_MM + 1) / PX_PER_MM) ** 2)
    g /= g.sum()
    e2 = len(g) // 2
    ext = np.concatenate([med[-e2:], med, med[:e2]])
    sm = np.convolve(ext, g, "valid")
    out = p + nrm * sm[:, None]
    q = 2
    x0, y0 = np.floor(out.min(0)) - 2
    w_, h_ = (np.ceil(out.max(0)) - np.floor(out.min(0)) + 4).astype(int)
    m = np.zeros((h_ * q, w_ * q), np.uint8)
    cv2.fillPoly(m, [np.round((out - [x0, y0]) * q * 16).astype(np.int32).reshape(-1, 1, 2)], 255,
                 lineType=cv2.LINE_8, shift=4)
    ks = max(3, int(round(spike_mm * PX_PER_MM * q)) | 1)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ks, ks)))
    cc, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cc:
        return p.reshape(-1, 1, 2)
    c2 = max(cc, key=cv2.contourArea).reshape(-1, 2).astype(np.float32)
    out = (c2 + 0.5) / q - 0.5 + [x0, y0]
    return out.reshape(-1, 1, 2).astype(np.float32)


def orient_rect(pts_mm):
    """Length x width box in mm. For items with straight edges (cards, plates, phones)
    the box follows those edges exactly; a small bump cannot tilt it."""
    pts = np.asarray(pts_mm, np.float32).reshape(-1, 2)
    rect = cv2.minAreaRect(pts)
    poly = cv2.approxPolyDP(pts.reshape(-1, 1, 2), 0.5, True).reshape(-1, 2)
    if len(poly) < 4:
        return rect
    seg = np.roll(poly, -1, 0) - poly
    ln = np.hypot(seg[:, 0], seg[:, 1])
    ang = np.degrees(np.arctan2(seg[:, 1], seg[:, 0])) % 90.0
    keep = ln >= 3.0
    if not keep.any():
        return rect
    hist = np.zeros(360)
    np.add.at(hist, (ang[keep] * 4).astype(int) % 360, ln[keep])
    sm = sum(np.roll(hist, k) for k in range(-4, 5))
    b = int(np.argmax(sm))
    if sm[b] < 0.35 * ln.sum():
        return rect
    a0 = (b + 0.5) / 4.0
    sel = keep & (np.abs(((ang - a0) + 45) % 90 - 45) <= 1.25)
    if ln[sel].sum() <= 0:
        return rect
    da = ((ang[sel] - a0 + 45) % 90) - 45
    a_dom = a0 + float(np.average(da, weights=ln[sel]))
    if abs(((rect[2] - a_dom) + 45) % 90 - 45) <= 1.0:
        return rect
    th = np.radians(a_dom)
    u = np.array([np.cos(th), np.sin(th)], np.float32)
    v = np.array([-np.sin(th), np.cos(th)], np.float32)
    pu, pv = pts @ u, pts @ v
    cu, cv_ = (pu.max() + pu.min()) / 2, (pv.max() + pv.min()) / 2
    c = u * cu + v * cv_
    return ((float(c[0]), float(c[1])), (float(pu.max() - pu.min()), float(pv.max() - pv.min())),
            float(np.degrees(th)))
