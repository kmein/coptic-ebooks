<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
  xmlns:tei="http://www.tei-c.org/ns/1.0">
  <xsl:output method="text" indent="no" encoding="UTF-8" />

  <xsl:template match="/">
#let bilingual = (coptic, translation) => grid(
  columns: (2fr, 1fr), column-gutter: 10pt,
  par(leading: 1em, coptic), par(leading: 0.6em, text(8pt, luma(15%), translation))
)

<xsl:apply-templates select="//tei:body/tei:div1" />
  </xsl:template>

  <xsl:template match="tei:div1">
#let copticText = ()
#let translationText = ()

     <xsl:apply-templates select=".//tei:p"/>

#bilingual(copticText.join(" "), strong("<xsl:value-of select="@n"/>") + [ ] + translationText.join(" "))

  </xsl:template>

  <xsl:template match="tei:p">
    #{
      copticText.push("<xsl:apply-templates select="tei:s/tei:phr" />")
      translationText.push("<xsl:value-of select="normalize-space(tei:s/@style)" />")
    }
  </xsl:template>

  <xsl:template match="tei:phr">
    <xsl:apply-templates select="tei:w"/>
    <xsl:if test="following-sibling::tei:phr">
      <xsl:text> </xsl:text>
    </xsl:if>
  </xsl:template>

  <xsl:template match="tei:w">
    <xsl:for-each select="node()[not(self::tei:pb)]">
      <xsl:value-of select="normalize-space(.)"/>
    </xsl:for-each>
  </xsl:template>
</xsl:stylesheet>
