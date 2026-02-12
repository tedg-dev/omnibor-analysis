---
description: Reminder to stop DigitalOcean droplet when done for the day
---

# DigitalOcean Droplet Shutdown Reminder

At the **end of every work session** (when the user says they're done, wrapping up,
or about to close/sleep their laptop), Cascade **must** remind the user:

> **Don't forget to stop your DigitalOcean droplet!**
> Go to [cloud.digitalocean.com](https://cloud.digitalocean.com) → Droplets →
> `omnibor-build` → Power → **Turn off droplet**.
>
> A stopped droplet still charges for disk ($0.007/hr) but not CPU.
> To stop all charges, **destroy** the droplet (you can recreate it later).

## When to Trigger

- User says "done for the day", "wrapping up", "going to sleep", "signing off", etc.
- User says they're closing or sleeping their laptop
- End of a long session where the droplet was used

## Droplet Details

- **Name:** omnibor-build
- **IP:** 137.184.178.186
- **SSH alias:** `omnibor-build` (configured in ~/.ssh/config)
- **Provider:** DigitalOcean
- **Cost:** ~$0.018/hr running, ~$0.007/hr stopped (disk only), $0 destroyed
