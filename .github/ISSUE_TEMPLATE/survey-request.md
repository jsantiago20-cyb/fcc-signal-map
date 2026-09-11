---
name: Survey request
about: Ask for a coverage survey around a coordinate
title: "Survey request: "
labels: survey-request
---

at: 39.7392, -104.9847
radius: 50
spacing: 2.5

Put your own coordinate on the `at` line; any format the map accepts works.
Radius is in miles, 5 to 100. Spacing is the gap between sample points, 1 to 10
miles. The two together have to stay under 3,000 samples, which is roughly
`3.6 * (radius / spacing)^2`.

The map page fills this in for you: search a coordinate there and click **Build
this survey**.
