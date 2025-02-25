<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
  xmlns:tei="http://www.tei-c.org/ns/1.0">
  <xsl:output method="text" indent="no" encoding="UTF-8" />

  <xsl:template match="/">
#let bilingual = (coptic, translation) => columns(2, coptic + colbreak() + text(0.7em, translation))

== <xsl:apply-templates select="//tei:titleStmt/tei:title" />

#let copticText = ""
#let translationText = ""

<xsl:apply-templates select="//tei:body" />

#grid(columns: (2fr, 1fr), row-gutter: 1em, column-gutter: 1em, copticText, par(leading: 0.4em, text(7pt, translationText)))

  </xsl:template>

  <xsl:template match="tei:p">
    #{
      copticText += [<xsl:apply-templates select="tei:s/tei:phr" /> ]
      translationText += [<xsl:value-of select="tei:s/@style" /> ]
    }
  </xsl:template>

  <xsl:template match="tei:phr"><xsl:apply-templates select="tei:w" /><xsl:text> </xsl:text></xsl:template>

  <xsl:template match="tei:w">
    <xsl:for-each select="node()[not(self::tei:pb)]">
      <xsl:value-of select="normalize-space(.)" />
    </xsl:for-each>
  </xsl:template>
</xsl:stylesheet>
