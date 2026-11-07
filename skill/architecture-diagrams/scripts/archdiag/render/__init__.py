"""Renderers: turn a laid-out ViewGraph into SVG plus each style's editable file.

* ``common``  - SVG helpers every style shares: escaping, text sizes, line types, legend,
  notes and the icon set.
* ``style_a`` - pictorial icons grouped by repo or application, with a ``.drawio`` file.

Every SVG keeps to what Word and PowerPoint draw: no ``<filter>``, ``<style>``, ``<use>``,
``<marker>`` or ``<image>``; presentation attributes only; arrowheads are polygons.
"""
from __future__ import annotations
