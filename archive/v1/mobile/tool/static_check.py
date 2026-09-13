"""Static sanity check for the Flutter app - no SDK available in this env.

Checks what a compiler would catch first: unbalanced delimiters, imports that
point at files that do not exist, identifiers referenced from a file that
neither declares nor imports them, and Strings.* uses with no constant.
"""
import pathlib, re, sys

root = pathlib.Path(__file__).resolve().parent.parent
lib = root / "lib"
files = sorted(lib.rglob("*.dart")) + sorted((root / "test").rglob("*.dart"))
problems = []


def strip(text: str) -> str:
    text = re.sub(r"'''.*?'''|\"\"\".*?\"\"\"", "''", text, flags=re.S)
    text = re.sub(r"(?<!\\)'(?:\\.|[^'\\\n])*'", "''", text)
    text = re.sub(r'(?<!\\)"(?:\\.|[^"\\\n])*"', '""', text)
    text = re.sub(r"//[^\n]*", "", text)
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


declared_strings = set()
strings_file = (lib / "core/strings.dart").read_text()
for match in re.finditer(r"static const (\w+)\s*=", strings_file):
    declared_strings.add(match.group(1))

declared_types: dict[str, str] = {}
for path in files:
    for match in re.finditer(
        r"^(?:abstract final |abstract |final |sealed )?class (\w+)",
        path.read_text(),
        re.M,
    ):
        declared_types[match.group(1)] = str(path)

for path in files:
    raw = path.read_text()
    code = strip(raw)

    for opener, closer in (("(", ")"), ("[", "]"), ("{", "}")):
        if code.count(opener) != code.count(closer):
            problems.append(
                f"{path}: unbalanced {opener}{closer} "
                f"({code.count(opener)} vs {code.count(closer)})"
            )

    imports = re.findall(r"import '([^']+)'", raw)

    def resolve(target: str) -> pathlib.Path | None:
        """A relative path, or the package's own absolute import into lib/."""
        if target.startswith("package:fleetbeat_driver/"):
            return (lib / target.split("/", 1)[1]).resolve()
        if target.startswith(("package:", "dart:")):
            return None
        return (path.parent / target).resolve()

    for target in imports:
        resolved = resolve(target)
        if resolved is not None and not resolved.exists():
            problems.append(f"{path}: import does not resolve -> {target}")

    for name in sorted(set(re.findall(r"Strings\.(\w+)", code))):
        # A leading underscore is a private member (e.g. the ._ constructor).
        if not name.startswith("_") and name not in declared_strings:
            problems.append(f"{path}: Strings.{name} is not declared")

    # Types used but neither declared here nor reachable via a local import.
    local = {str(r) for r in (resolve(t) for t in imports) if r is not None}
    here = {n for n, p in declared_types.items() if p == str(path)}
    for name in sorted(set(re.findall(r"\b([A-Z][A-Za-z0-9]+)\b", code))):
        if name in declared_types and name not in here:
            if declared_types[name] not in local:
                problems.append(
                    f"{path}: uses {name} but does not import "
                    f"{pathlib.Path(declared_types[name]).name}"
                )

print(f"checked {len(files)} dart files")
for problem in sorted(set(problems)):
    print("  ✗", problem)
print("OK" if not problems else f"{len(set(problems))} problem(s)")
sys.exit(1 if problems else 0)
