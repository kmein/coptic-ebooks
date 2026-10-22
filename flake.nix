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
      python = pkgs.python3.withPackages (ps: [ ps.fonttools ]);
      libertinus = "${pkgs.libertinus}/share/fonts/opentype";

      makeEpubPackage =
        dir:
        pkgs.runCommand "${dir}.epub" { } ''
          ${python}/bin/python3 ${./epub}/build.py "${copticscriptorium}/${dir}" $out \
            --coptic-font ${pkgs.noto-fonts}/share/fonts/noto/NotoSansCoptic-Regular.otf \
            --serif-font ${libertinus}/LibertinusSerif-Regular.otf \
            --serif-italic-font ${libertinus}/LibertinusSerif-Italic.otf \
            --serif-bold-font ${libertinus}/LibertinusSerif-Bold.otf \
            --fallback-font ${pkgs.dejavu_fonts.minimal}/share/fonts/truetype/DejaVuSans.ttf \
            --typst ${pkgs.typst}/bin/typst
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

      # Corpora with a TreeTagger export (a `*_TT` directory or `*_TT.zip`), the EPUB source
      ttCorpora = builtins.filter (
        name:
        let
          entries = builtins.readDir "${copticscriptorium}/${name}";
        in
        builtins.any (e: pkgs.lib.hasSuffix "_TT" e || pkgs.lib.hasSuffix "_TT.zip" e) (
          builtins.attrNames entries
        )
      ) (builtins.attrNames (pkgs.lib.filterAttrs (_: type: type == "directory") (builtins.readDir copticscriptorium)));

      epubPackages = builtins.listToAttrs (
        map (dir: {
          name = dir + "-epub";
          value = makeEpubPackage dir;
        }) ttCorpora
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
