// EPUB cover, rendered to a 1600×2560 PNG by build.py (--ppi 256).
// Data comes from cover.json: title, author, subtitle, incipit.
#let d = json("cover.json")
#let red = rgb("#7d2418")
#let ink = rgb("#2a1c12")

#set page(width: 6.25in, height: 10in, margin: 0pt, fill: rgb("#f1e8d5"))
#set text(font: "Libertinus Serif", fill: ink, lang: "en", hyphenate: false)
#set par(leading: 0.4em)

#place(top + left, dx: 0.3in, dy: 0.3in,
  rect(width: 5.65in, height: 9.4in, stroke: 2.4pt + red))
#place(top + left, dx: 0.4in, dy: 0.4in,
  rect(width: 5.45in, height: 9.2in, stroke: 0.7pt + red))

#let ornament = box(width: 55%, grid(
  columns: (1fr, auto, 1fr),
  align: horizon,
  column-gutter: 9pt,
  line(length: 100%, stroke: 0.7pt + red),
  rotate(45deg, square(size: 6pt, fill: red)),
  line(length: 100%, stroke: 0.7pt + red),
))

#block(width: 100%, height: 100%, inset: (x: 0.8in, top: 0.95in, bottom: 0.85in))[
  #set align(center)
  #text(size: 10.5pt, tracking: 0.32em, fill: red)[COPTIC SCRIPTORIUM]
  #v(1fr)
  #if d.incipit != "" [
    #text(font: "Noto Sans Coptic", size: 26pt, fill: red, d.incipit)
    #v(0.45in)
  ]
  #ornament
  #v(0.4in)
  #text(size: 38pt, d.title)
  #if d.author != "" [
    #v(0.25in)
    #text(size: 17pt, tracking: 0.06em, smallcaps(d.author))
  ]
  #v(0.4in)
  #ornament
  #v(1fr)
  #text(size: 13pt, style: "italic", d.subtitle)
]
