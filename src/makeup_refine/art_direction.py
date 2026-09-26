"""Shared aesthetic constraints; human preference still decides acceptance."""

PLANNING_DIRECTION = (
    "Judge the full-face balance before proposing individual edits. "
    "In each rationale name a visible makeup issue and explain how the correction improves "
    "proportion, edge quality or coordination with the rest of the existing look. "
    "More pigment, greater symmetry or greater visibility is not itself an improvement. "
    "Do not automatically deepen lips, lift every wing, or fill every editable region. "
    "Choose only useful changes; avoid making eyes and lips competing focal points. "
    "Respect natural asymmetry and the person's existing makeup style. "
)

RENDERING_DIRECTION = (
    "Art direction: coherent makeup with intentional placement and well-finished edges. "
    "Full-strength means a legible technique, not exaggerated width, length or darkness. "
    "Use the mask as an allowed boundary, never as a shape to fill. "
    "Eyeliner must connect smoothly to the lash line and taper to a fine tip; no blunt hooks, "
    "detached strokes, uniformly thick wings or dark blocks in the eyelid fold. "
    "Eyeshadow must have a graduated outer edge that fades into the existing skin; "
    "no solid patch, stripe, or pigment filling the entire brow-to-lash space. "
    "Lip-boundary corrections must blend inward into the existing lipstick, with no contrasting "
    "dark perimeter, doubled contour or overlining beyond the natural lip edge. "
    "Do not draw an artificial smile or move the anatomical mouth corners. "
    "Keep the eyes and lips coordinated in contrast and finish. "
    "Compositing controls intensity later; it cannot repair a poorly designed shape. "
)
