# Garmin activity reclassifier (systemd timer)

Finds your custom "football" activity after it syncs and relabels it in
Garmin Connect. Runs once a day via a systemd timer rather than a true
webhook, since Garmin doesn't offer push notifications to individual
developers — a daily scan easily covers "played football yesterday, want it
relabeled by today."

This uses the **unofficial** `garminconnect` Python library, which logs in
through the same session Garmin Connect's website uses. It can change
without notice and isn't an integration Garmin supports, so treat it as a
personal-project tool, not something to depend on for anything critical.

## 1. Deploy the code

```bash
sudo mkdir -p /opt/garmin-reclassify
sudo cp reclassify.py requirements.txt /opt/garmin-reclassify/
cd /opt/garmin-reclassify
sudo python3 -m venv venv
sudo ./venv/bin/pip install -r requirements.txt
```

Create a dedicated unprivileged user to run it as (matches the `User=` line
in the service unit):

```bash
sudo useradd --system --home /opt/garmin-reclassify --shell /usr/sbin/nologin garmin-reclassify
sudo chown -R garmin-reclassify:garmin-reclassify /opt/garmin-reclassify
```

## 2. One-time interactive login

Garmin will ask for MFA on a fresh login. Do this once, interactively, as
the service user — not from inside the timer, which runs headlessly and
can't answer an MFA prompt:

```bash
sudo -u garmin-reclassify env GARMIN_EMAIL="you@example.com" GARMIN_PASSWORD="yourpassword" \
  /opt/garmin-reclassify/venv/bin/python /opt/garmin-reclassify/reclassify.py --login-only
```

This creates `~/.garmin-reclassify/tokens` under that user's home — that's
what lets the daily automated run skip MFA afterwards.

## 3. Find the exact target type key

Garmin's activity type list is internal and undocumented, so look it up
directly:

```bash
sudo -u garmin-reclassify env GARMIN_EMAIL=... GARMIN_PASSWORD=... \
  /opt/garmin-reclassify/venv/bin/python /opt/garmin-reclassify/reclassify.py --list-types
```

Find the football-related `typeKey` (may be something like
`american_football`, or your custom profile may need to map to a close
built-in type — there's no guarantee a dedicated "football" type exists
server-side even though your watch profile is named that).

## 4. Configure the env file

```bash
sudo cp garmin-reclassify.env.example /etc/garmin-reclassify.env
sudo chown root:root /etc/garmin-reclassify.env
sudo chmod 600 /etc/garmin-reclassify.env
sudo nano /etc/garmin-reclassify.env   # fill in email, password, TARGET_TYPE_KEY, and a source filter
```

`SOURCE_MATCH_NAME` (substring of the activity name) or `SOURCE_TYPE_KEY`
(the typeKey Garmin currently assigns it, often `other`) — at least one is
required, so the script can't accidentally relabel everything.

Test first with `DRY_RUN=1` in the env file — it logs what it would change
without writing anything.

## 5. Install the systemd units

```bash
sudo cp garmin-reclassify.service garmin-reclassify.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now garmin-reclassify.timer
```

Check it's scheduled and see the next run time:

```bash
systemctl list-timers garmin-reclassify.timer
```

Trigger a run immediately to test, without waiting for midnight:

```bash
sudo systemctl start garmin-reclassify.service
journalctl -u garmin-reclassify.service -n 50 --no-pager
```

`OnCalendar=*-*-* 00:00:00` fires at midnight **server local time**. If the
host is in a different timezone than you expect, check with `timedatectl`
and adjust, or use `OnCalendar=*-*-* 00:00:00 America/New_York`-style
explicit timezone syntax.

## Notes / limitations

- This is reverse-engineered, not an official integration — Garmin can
  change the underlying endpoints at any time and break it.
- Your Garmin password lives in `/etc/garmin-reclassify.env` — keep that
  file's permissions locked to root-only (600), as set above.
- If Garmin ever adds native support for football on the Forerunner 165,
  this whole workaround becomes unnecessary.
