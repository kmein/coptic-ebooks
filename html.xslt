<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
  xmlns:tei="http://www.tei-c.org/ns/1.0">
  <xsl:output method="html" indent="yes" encoding="UTF-8" />

  <xsl:template match="/">
    <html>
      <head>
        <title>
          <xsl:apply-templates select="//tei:titleStmt/tei:title" />
        </title>
      </head>
      <body>
        <h1>
          <xsl:apply-templates select="//tei:titleStmt/tei:title" />
        </h1>
        <table>
          <tbody>
            <xsl:apply-templates select="//tei:body" />
          </tbody>
        </table>
      </body>
    </html>
  </xsl:template>

  <xsl:template match="tei:p">
    <tr>
      <td class="coptic">
        <xsl:apply-templates select="tei:s/tei:phr" />
      </td>
      <td class="translation">
        <xsl:value-of select="tei:s/@style" />
      </td>
    </tr>
  </xsl:template>


  <xsl:template match="tei:phr"><xsl:apply-templates select="tei:w" /><xsl:text> </xsl:text></xsl:template>

  <xsl:template match="tei:w">
    <xsl:for-each select="node()[not(self::tei:pb)]">
      <xsl:value-of select="normalize-space(.)" />
    </xsl:for-each>
  </xsl:template>
</xsl:stylesheet>
