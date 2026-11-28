# Spec: rename the product to "Spunfection Studio" (user-facing only)

**For:** Claude Code, working in the drape repo.
**Decision (Tyler, 2026-11-22):** the product is now **Spunfection Studio™**, published by **Spunfection LLC**, hosted at **spunfection.studio**. "Spunfection" is a made-up word, so it can be trademarked; "drape" can't.

**Scope:** change everything a **user sees**. Keep the internal code identity: the Python package `drape`, module names, import paths, CLI module `python -m drape.studio`, test names, file names inside the repo, and git history. Renaming internals is busywork and breaks things.

---

## 1. Naming rules

- **Product name:** "Spunfection Studio". Short form in tight UI spots: "Spunfection".
- **Trademark symbol:** "Spunfection Studio™" **once per surface**: the first or most prominent use on the site header/landing, the README title, the PDF and tech-pack footer, and the about box. Elsewhere, plain "Spunfection Studio". Never use "®" (not registered yet).
- **Company:** "Spunfection LLC" wherever a legal owner is named (licence header, terms, footer, copyright lines, PDF footers).
- **Domain:** `spunfection.studio` in links, canonical URLs, Open Graph tags, and "made with" lines.
- **The word "drape":** keep it as an ordinary verb and noun in the UI ("Drape again", "the drape", "drape on your avatar"). It's a sewing term; only its use as the product's name goes away. The 3D step label "Try on" stays.
- **Don't use other products' names** anywhere user-facing, including meta descriptions and the README.

## 2. What to change

Grep for user-facing occurrences of `drape studio`, `drape Studio`, `Drape Studio`, `drape` used as a product name, `drape.studio`, and the old tab title. Then change:

1. **Studio UI** (`drape/studio/static/index.html`, `js/*.js`, `css`):
   - `<title>`, the header logo text, and the ALPHA badge line;
   - the about/help box (`11_help.js`), the first-visit alpha popup, the alpha banner;
   - the version text ("Spunfection Studio v1.5 alpha").
2. **Favicon, logo and app manifest:** name and short_name in the manifest, if present. Keep the current icon unless Tyler supplies a new one.
3. **Meta tags:** `description`, Open Graph `og:title`/`og:site_name`/`og:url`, Twitter card, canonical link → `https://spunfection.studio/`.
4. **Generated files people keep**:
   - print PDF footer: "Made with Spunfection Studio™ · spunfection.studio";
   - projector PDF;
   - tech pack title page and footer;
   - DXF header comment/text (a TEXT entity on a non-cut layer, or the header comment; never on cut layers);
   - glTF `asset.generator` → "Spunfection Studio <version>";
   - sewing-instructions header;
   - saved design files: add `"app": "Spunfection Studio"` next to the existing format/version stamp, and keep reading old files with no `app` field.
5. **Server and launcher:** the console banner, the `packaging/launcher.py` window and menu names, the `--share` message text.
6. **Docs:**
   - README title and intro: "Spunfection Studio™: free, open-source 2D sewing patterns → 3D drape in your browser. By Spunfection LLC."
   - Add a line: "The code package is named `drape`."
   - `THIRD_PARTY_NOTICES.md` heading, `CLAUDE.md` (a short "Naming" section with these rules), `HOW_TO_RUN`.
   - Copyright lines: "© 2026 Spunfection LLC".
7. **`pyproject.toml`:** keep `name = "drape"` for the package; set `description` to mention Spunfection Studio; add `authors`/`maintainers` = "Spunfection LLC". No personal email anywhere (see section 4).
8. **Web build (`tools/build_web_proof.py` and the Cloudflare Pages build):** the output `index.html` title, meta tags and footer; a `_headers` or `_redirects` file only if needed for the domain.

## 3. Footer and legal text

Add one site footer, used on every page:

> © 2026 Spunfection LLC · Spunfection Studio™ is alpha software, provided as-is · [Terms] · [Privacy] · [Source code] · [Report a bug]

- **[Source code]** links to the public repo. The AGPL requires it if that licence is chosen; keep the link either way.
- **[Report a bug]** links to GitHub Issues.
- **[Terms] / [Privacy]** link to `/terms` and `/privacy` placeholder pages that say "Coming before public launch" if they're not written yet. Tyler will supply the text.

## 4. Privacy guard (must hold)

- **No personal email address** anywhere in the repo, the site, generated files or package metadata. Contacts are GitHub Issues or a future project alias.
- Add a test that greps the repo (excluding `.git`) and the built web output for the owner's personal email domain and for any email address pattern outside an allowlist (`noreply@`, example.com). It fails if one is found.

## 5. Tests (`tests/test_v22_rename.py`)

1. The studio page `<title>` and header contain "Spunfection Studio"; "™" appears exactly once in the header area.
2. No user-facing string uses "drape" as the product name: grep built HTML/JS for `drape studio` (case-insensitive) and `drape.studio`, which must be 0. Allow "drape" as a verb or noun.
3. The PDF export footer contains "Spunfection Studio" and "spunfection.studio". The glTF `asset.generator` starts with "Spunfection Studio". The tech pack footer contains "Spunfection LLC".
4. Saved designs include `"app": "Spunfection Studio"`. An old design without the field still loads.
5. The footer has working links (Terms, Privacy, Source, Report a bug) to the right targets.
6. The privacy grep from section 4.
7. No competitor names in user-facing text or meta tags.
8. The existing test suite still passes. The Python package name and imports are unchanged.

## 6. Don'ts

- Don't rename the `drape` package, modules, CLI or repo folders.
- Don't add "®".
- Don't touch git history.
- Don't change behaviour or physics. This is text, metadata and links only.

## 7. Report back to Tyler

Send:
- screenshots of the studio header, the alpha banner and the footer;
- a printed PDF footer;
- the README top section;
- a list of every file changed;
- any place "drape" was left as the product name on purpose, and why.
