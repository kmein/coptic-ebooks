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
          src: url("${pkgs.eb-garamond}/share/fonts/opentype/EBGaramond08-Regular.otf");
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
          font-family: "Garamond";
          font-size: 0.7em;
          width: 33%;
          color: #888;
        }
      '';

      makeEpubPackage =
        dir:
        pkgs.runCommand "${dir}.epub" { } ''
          root="${copticscriptorium.outPath}/${dir}"

          dir_out=$(mktemp -d)

          ${pkgs.findutils}/bin/find "$root" -name '*.xml' | sort | while read -r xml_file; do
            ${pkgs.saxon-he}/bin/saxon-he -s:"$xml_file" -xsl:${./html.xslt} -o:"$dir_out/$(basename $xml_file .xml).html"
          done

          ${pkgs.pandoc}/bin/pandoc $dir_out/*.html \
            -o $out \
            --css ${pkgs.writeText "style.css" css} \
            --epub-embed-font=${ifao-grec}/IFAOGrec.ttf \
            --epub-embed-font=${pkgs.eb-garamond}/share/fonts/opentype/EBGaramond08-Regular.otf \
            -V title="Coptic Scriptorium - ${dir}"
        '';


      makePdfPackage =
        dir:
        pkgs.runCommand "${dir}.pdf" { } ''
          root="${copticscriptorium.outPath}/${dir}"

          ${pkgs.findutils}/bin/find "$root" -name '*.xml' | sort | while read -r xml_file; do
            ${pkgs.saxon-he}/bin/saxon-he -s:"$xml_file" -xsl:${./typst.xslt} -o:"$(basename $xml_file .xml).typ"
          done

          files=$(ls -1 *.typ | ${pkgs.jq}/bin/jq -R . | ${pkgs.jq}/bin/jq -s .)

          cat <<EOF > scriptorium.typ
          #set text(font: ("Noto Sans Coptic", "Noto Sans"))
          #set par(justify: true)
          #for chapter in json.decode(sys.inputs.files) {
            include chapter
          }
          EOF

          ${pkgs.typst}/bin/typst compile --font-path=${ifao-grec}:${pkgs.noto-fonts}/share/fonts/noto --input="files=$files" scriptorium.typ $out
        '';


      # Discover all subdirectories in copticscriptorium and generate packages
      subdirs = builtins.filter (name: builtins.pathExists (copticscriptorium.outPath + "/${name}")) (
        builtins.attrNames (builtins.readDir copticscriptorium.outPath)
      );

      epubPackages = builtins.listToAttrs (
        map (dir: {
          name = dir + "-epub";
          value = makeEpubPackage dir;
        }) subdirs
      );
      pdfPackages = builtins.listToAttrs (
        map (dir: {
          name = dir + "-pdf";
          value = makePdfPackage dir;
        }) subdirs
      );

    in
    {
      packages.x86_64-linux = epubPackages // pdfPackages;
    };
}
