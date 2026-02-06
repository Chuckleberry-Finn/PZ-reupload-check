# Project Zomboid Mod Reupload Tracker

## Overview
This tool helps mod authors find and report unauthorized copies of their mods on Steam Workshop. The interface is organized into three columns that flow from left to right:

**Tracked Mods** → **Search Results** → **DMCA Manager**

---

## Getting Started
1. Double-click `DMCA-Tracker.exe` or run `startWin.bat`.
2. A web page opens in your browser with three columns.

---

## Column 1: Tracked Mods (Left)

This is where you add the mods you want to protect.

### Adding Mods Manually
1. Click **"+ Add Mod"**.
2. Enter your **Mod ID** (e.g., `SkillRecoveryJournal`).
3. Optionally enter your **Workshop ID** to mark your original.
4. Changes save automatically.

### Fetching from a Steam Profile
1. Click **"Fetch"**.
2. Enter a Steam profile URL or ID.
3. All mods from that profile are added automatically.

### Managing Your List
- **Export** - Save your tracked mods to a JSON file.
- **Import** - Load mods from a JSON file.
- **Import Profile** - Copy mods from another profile in this tool.
- **Delete** - Hold the × button to remove a mod.

---

## Column 2: Search Results (Middle)

This shows Workshop items that match your tracked mods.

### Running Searches
- Click **"Run All Searches"** to search for all tracked mods.
- Each mod search appears as a task in the queue (tally marks in status bar).
- Click a single mod's **"Search"** button to search just that one.

### Adding Items Manually
Click **"+ Manual"** to add a Workshop item by URL or ID. Useful for items that don't appear in search results.

### Understanding the Colors
| Color | Meaning |
|-------|---------|
| **Gold** | Your original mod (matches your Workshop ID) |
| **Green** | Approved copy (legitimate/permitted) |
| **Teal** | Manually added item |
| **Orange border** | Pending DMCA (not yet filed) |
| **Purple** | DMCA filed |
| **Purple (dark)** | Taken down by Steam |

### Filtering Results
- **Hide Approved** - Show only unapproved items.
- **Sort** - Order results by date, title, or match count.
- **Hide Zero** - Hide mods with no results.

### Taking Action
- **+ Approve** - Mark a copy as legitimate.
- **+ DMCA** - Add to DMCA Manager for reporting.

---

## Column 3: DMCA Manager (Right)

This is where you manage items you want to report to Steam.

### Viewing Entries
Filter your list with these options:
- **Pending Only** - Items not yet filed.
- **Filed Only** - Items you've reported.
- **Taken Down Only** - Items Steam has removed.

### Verification
Verify that Workshop items actually contain your files before filing.

**Setup (one-time):**
1. Download [DepotDownloader](https://github.com/SteamRE/DepotDownloader)
2. Click **"Configure"** and point to the executable
3. Enter your Steam credentials when/if prompted

**Using Verification:**
- **Verify All** - Check all pending entries
- **Verify** (per item) - Check a single entry
- Results show match percentage (High/Medium/Low/None)

### Filing a DMCA Notice

**Warning:** Filing false DMCA claims may result in legal penalties. Always verify the work is yours.

1. Click **"Copy DMCA Message"** - copies pre-formatted text which includes all links to matching mods found. (This message can be split up between the 2 fields in Steam's DMCA form.)
2. Click **"File"** - opens Steam's DMCA form.
3. Paste the message (it has two parts for different form sections).
4. Fill out your personal information.
5. Submit to Steam.
6. Return here and click **"Mark Filed"**.

### Checking Results
1. Wait several days for Steam to review.
2. Click **"Re-check Filed"** to check status of all filed items.
3. Items removed by Steam will show as **"TAKEN DOWN"**.

### Buttons Reference
| Button | Action |
|--------|--------|
| **Copy DMCA Message** | Copy report text to clipboard |
| **File** | Open Steam's DMCA form |
| **Mark Filed** | Record that you've submitted |
| **Verify** | Check single item for your files |
| **×** | Remove from DMCA list |

### Exporting/Importing
- **Export DMCA** - Save your DMCA list to a file.
- **Import DMCA** - Load a saved DMCA list.

---

## Profiles

Profiles let you maintain separate tracking lists (e.g., for different mod collections).

### Managing Profiles
1. Click the menu button (**⋮**) next to the profile dropdown.
2. Options:
   - **New Profile** - Create a fresh list.
   - **Rename** - Change profile name.
   - **Delete** - Remove a profile (hold to confirm).

### Profile Data
Each profile stores:
- Tracked mods
- Search results
- DMCA entries
- Manually added items
- Filter settings

---

## Task Queue

The status bar shows task progress with colored tally marks:

| Color | Task Type |
|-------|-----------|
| **Dark Red** | Search |
| **Dark Blue** | Verification |
| **Purple** | Re-check filed |
| **Teal** | Manual add |

- **Pulsing** = Currently running
- **Faded** = Completed (disappears after 3 seconds)
- **Dim** = Queued/waiting

Click **Pause/Resume** to control the queue.

---

## Tips

1. **Start with Fetch** - If you have a Steam profile with all your mods, use Fetch to add them quickly.
2. **Verify before filing** - Use the verification feature to confirm matches.
3. **Export regularly** - Back up your data with the Export buttons.
4. **Be patient** - Steam can take days to weeks to process DMCA notices.
5. **Check the queue** - Watch the tally marks to track search/verify progress.
