# Project Zomboid Mod Tracker - User Guide

## What Does This Tool Do?
This tool helps you find unauthorized copies of your mods on Steam Workshop.

---

## Step 1: Start the Tool
1. Double-click the `DMCA-Tracker.exe` to open it, or run `startWin.bat`.
2. A web page will open in your browser.
3. You'll see 3 columns/panels.

---

## Step 2: Add Your Mods

### What You Need:
- **Mod ID** - The modID of your mod (like "SkillRecoveryJournal").
- **Profile Link/ID** - You can select Fetch to pull all of a profile's mods.

### How to Add:
1. Click the **"+ Add Mod"** button
2. Type your Mod ID in the first box
3. Type your Workshop ID in the second box (optional but helpful)
4. Click away from the box - it saves automatically!

**Or**

1. Select **Fetch** and type in a profile's ID/URL

### Add More Mods:
- Click **"+ Add Mod"** again for each mod you want to track

---

## Step 3: Search for Copies
1. Click the **"Run All Searches"** button.
2. Wait while the tool looks on Steam.
3. Results will show up in the middle column.

---

## Step 4: Look at the Results

### What the Colors Mean:
- **Gold/Yellow** = Your original mod (based on matching workshopID)
- **Green** = Copies you have approved
- **No color** = Copies that have not been marked
- **Purple/Blue** = DMCA filed

---

## Step 5: Mark Bad Copies
1. Find the mod that looks suspicious.
2. Click the **"+ DMCA"** button next to it
3. It moves to the DMCA Manager section

---

## Step 6: File a Complaint with Steam

### Before You Start:
Verify that the work is in fact your own. While the automatic verification system uses hashes and can be very thorough, you should still verify manually.

**Warning:** Filing false DMCA claims may result in legal penalties

### Steps to File a DMCA Notice:
1. Click **"Copy DMCA Message"** - this copies the text you need. This message actually has two parts, one for each section regarding context.
2. Click the **"File"** button - this opens Steam's form.
3. Paste your message, cut and paste the 2nd half into the relevant section, all into Steam's form.
4. Fill out personal information.
5. Submit the form to Steam.
6. Return to the tool and click **"Mark Filed"**.

---

## Step 7: Check if Steam Removed Items
1. Wait several days for Steam to review.
2. Click **"Re-check Filed"** button.
3. The tool will check the status of reported items.
4. Items marked **"TAKEN DOWN"** have been removed by Steam.

---

## Extra Features

### Verify (Advanced)
- This checks if copies really have your files inside.
- You need to download something called **DepotDownloader** first:
  - https://github.com/SteamRE/DepotDownloader
- Click the gear button (⚙) to set it up.
- Then click **"Verify"** to check.

### Profiles
- You can make different lists for tracking.
- Click the menu button (⋮) next to "Profile".
- Pick **"New Profile"** to make a new list.

### Exporting/Importing
- Click **"Export"** to save your mod/DMCA list to a JSON file.
- Click **"Import"** to load a saved list.
- This creates a backup of your data.
