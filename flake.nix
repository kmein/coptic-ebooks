{
  description = "A very basic flake";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";
    copticscriptorium.url = "github:copticscriptorium/corpora";
    copticscriptorium.flake = false;
  };

  outputs =
    {
      self,
      nixpkgs,
      copticscriptorium,
    }:
    {
      packages.x86_64-linux.default =
        let
          pkgs = nixpkgs.legacyPackages.x86_64-linux;
          ifao-grec = pkgs.fetchzip {
            url = "https://www.ifao.egnet.net/uploads/polices/IFAOGrecUnicode-v3.zip";
            stripRoot = false;
            hash = "sha256-qWnCCaY/yM0oyGjt/8tV+Sy/rMWRiN413zwgD/GWbpI=";
          };
          css = ''
            @font-face {
              font-family: "Garamond";
              font-style: normal;
              font-weight: normal;
              src: url("./Garamond.otf");
            }

            @font-face {
              font-family: "IFAO Grec";
              font-style: normal;
              font-weight: normal;
              src: url("${ifao-grec}/IFAOGrec.ttf");
            }

            body {
              font-family: "IFAO Grec", "Garamond", serif;
            }

            .coptic {
              width: 66%;
            }

            h1 {
              display: none
            }

            .translation {
              font-size: 0.7em;
              width: 33%;
              color: #888;
            }
          '';
        in
        pkgs.runCommand "martyrdom.epub" { } ''
          cp ${pkgs.eb-garamond}/share/fonts/opentype/EBGaramond08-Regular.otf Garamond.otf

          root="${copticscriptorium.outPath}/martyrdom-victor/martyrdom.victor_TEI"

          dir=$(mktemp -d)

          ${pkgs.findutils}/bin/find "$root" -name '*.xml' | sort | while read -r xml_file; do
            ${pkgs.saxon-he}/bin/saxon-he -s:"$xml_file" -xsl:${./coptic.xslt} -o:"$dir/$(basename $xml_file .xml).html"
          done

          ${pkgs.pandoc}/bin/pandoc $dir/*.html \
            -o $out \
            --css ${pkgs.writeText "style.css" css} \
            --epub-embed-font=${ifao-grec}/IFAOGrec.ttf \
            --epub-embed-font=Garamond.otf \
            -V title="Coptic Scriptorium"
        '';
    };
}
