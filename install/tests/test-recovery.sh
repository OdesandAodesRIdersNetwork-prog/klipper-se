#!/usr/bin/env bash
# Local fixture tests for returned-MCU recovery. No actual Moonraker or systemctl.
set -euo pipefail
here="$(cd -- "$(dirname -- "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/logs"
cat > "$tmp/bin/sleep" <<'SLEEP'
#!/usr/bin/env bash
exit 0
SLEEP
cat > "$tmp/bin/curl" <<'CURL'
#!/usr/bin/env bash
case " $* " in
  *'/printer/info'*)
    case "$TEST_INFO" in
      lost) printf '{"result":{"state":"shutdown","state_message":"Lost communication with MCU mcu"}}';;
      ready) printf '{"result":{"state":"ready","state_message":"Printer is ready"}}';;
      other) printf '{"result":{"state":"shutdown","state_message":"Heater failure"}}';;
      invalid) printf 'invalid';;
      unreachable) exit 7;;
    esac;;
  *'/printer/gcode/script'*) printf x >> "$TEST_POST_LOG";;
  *) exit 8;;
esac
CURL
chmod 755 "$tmp/bin/sleep" "$tmp/bin/curl"
cp "$here/recovery/v3se-mcu-recover.sh.in" "$tmp/recovery.sh"
python3 - "$tmp/recovery.sh" "$tmp" <<'PY'
import pathlib,sys
f=pathlib.Path(sys.argv[1]); d=sys.argv[2]
s=f.read_text().replace('@MCU_SERIAL_BY_ID@',d+'/mcu').replace('@MOONRAKER_URL@','http://127.0.0.1:7125').replace('@PRINTER_DATA@',d)
f.write_text(s)
PY
export PATH="$tmp/bin:$PATH" TEST_POST_LOG="$tmp/posted"
# Device missing: never attempt a firmware restart
export TEST_INFO=lost
bash "$tmp/recovery.sh"
test ! -e "$tmp/posted"
: > "$tmp/mcu"
for TEST_INFO in ready other invalid unreachable; do
    export TEST_INFO
    bash "$tmp/recovery.sh"
    test ! -e "$tmp/posted"
done
export TEST_INFO=lost
bash "$tmp/recovery.sh"
test "$(wc -c < "$tmp/posted")" -eq 1
printf 'PASS: recovery refuses absent MCU, unrelated/ready state, invalid or unreachable Moonraker; restarts only on verified lost MCU\n'
