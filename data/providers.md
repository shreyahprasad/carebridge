# Provider data review (SAMHSA, DC + 10 mi)

Source: SAMHSA FindTreatment.gov locator export, mental-health facilities within 10 miles of central DC, retrieved 2026-11-06. Cleaned by `scripts/clean_samhsa.py` into `data/providers.json`.

| Field | Count |
|---|---|
| Facilities | 72 |
| In DC / MD / VA / other | 26 / 29 / 16 / 1 |
| Missing coordinates (distance unknown) | 5 |
| In-person outpatient | 67 |
| Telehealth | 62 |
| Accepts Medicaid (own state) | 57 |
| …of those in DC | 25 |
| Sliding fee scale | 19 |
| Payment assistance | 11 |
| State plan other than Medicaid | 27 |
| Trauma program | 39 |
| PTSD program | 41 |
| Domestic-violence program | 12 |
| Serves children/adolescents | 55 |
| Spanish | 26 |
| Sign language | 14 |

**Languages besides English:** Spanish 26, French 9, Arabic 7, Farsi 5, Hindi 5, Chinese 4, Haitian Creole 4, Hebrew 4, Japanese 4, Vietnamese 4, German 3, Greek 3, Hmong 3, Italian 3, Korean 3, Polish 3, Portuguese 3, Russian 3, Tagalog 3, Ojibwa 1, Yupik 1

## Not in SAMHSA (ask on the call)
- Woman clinician available (`woman_clinician_available: null`)
- Interpreter services for unlisted languages (`interpreter_services: null`)
- Whether an MD/VA facility accepts **DC** Medicaid
- Current availability / waitlist
- Dari specifically (SAMHSA lists Farsi; Dari is closely related, confirm)

## Case 1 preview: Farsi speakers

| Facility | Where | In-person | Tele | Medicaid | Sliding/assist | Trauma | DV | Phone |
|---|---|---|---|---|---|---|---|---|
| Gio Health Services Inc | DC 20011 | ✓ | ✓ | ✓ |  | ✓ | ✓ | 202-621-8494 |
| Northern Virginia Family Services — Multicultural Center | VA 22042 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 571-748-2800 |
| Dr Goldberg and Associates PLLC — Stevenson Alexandria Office | VA 22304 | ✓ | ✓ |  |  |  |  | 703-935-0058 |
| Cornerstone Montgomery | MD 20814 | ✓ | ✓ | ✓ |  | ✓ |  | 301-493-4200 |
| Cornerstone Montgomery | MD 20902 | ✓ | ✓ | ✓ |  | ✓ |  | 301-493-4200 x2 |

Only one is in DC with Medicaid + in-person + trauma + DV: **Gio Health Services**.

## Case 2 preview: Spanish + serves under 18 + in-person (25; DC first)

| Facility | Where | In-person | Tele | Medicaid | Sliding/assist | Trauma | DV | Phone |
|---|---|---|---|---|---|---|---|---|
| Whitman Walker Health — Addiction Treatment Services | DC 20005 | ✓ | ✓ | ✓ |  | ✓ |  | 202-797-4453 |
| Therapeutic Links — Behavioral Health Services | DC 20036 | ✓ | ✓ | ✓ |  |  |  | 202-644-8904 |
| Childrens National Hospital — Department of Psychiatry | DC 20010 | ✓ | ✓ | ✓ |  | ✓ |  | 202-476-5000 |
| Gio Health Services Inc | DC 20011 | ✓ | ✓ | ✓ |  | ✓ | ✓ | 202-621-8494 |
| New Hope Health Services | DC 20032 | ✓ | ✓ | ✓ | ✓ | ✓ |  | 202-827-9961 |
| Whitman Walker Health — Max Robinson Center | DC 20032 | ✓ | ✓ | ✓ |  | ✓ |  | 202-797-4453 |
| Preventive Measures | DC 20020 | ✓ | ✓ | ✓ |  |  |  | 202-563-7632 |
| Rock Recovery | VA 22209 | ✓ | ✓ | ✓ | ✓ |  |  | 571-255-9906 |
| Arlington County Community Servs Board | VA 22204 | ✓ | ✓ | ✓ | ✓ | ✓ |  | 703-228-6551 |
| Bloom Health Centers | VA 22203 | ✓ | ✓ | ✓ |  |  |  | 703-594-7879 |
| Vesta Inc — Silver Spring | MD 20910 | ✓ | ✓ | ✓ |  | ✓ |  | 240-296-5858 |
| Montgomery County — Child/Adol Behav Health | MD 20910 | ✓ | ✓ | ✓ | ✓ | ✓ |  | 240-777-1450 |
| Counseling Center of Maryland | MD 20814 | ✓ | ✓ |  | ✓ | ✓ |  | 301-742-2282 |
| Alexandria Community Services Board | VA 22311 | ✓ | ✓ | ✓ | ✓ | ✓ |  | 703-746-3400 |
| Northern Virginia Family Services — Multicultural Center | VA 22042 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 571-748-2800 |
| Dr Goldberg and Associates PLLC — Old Town Alexandria Office | VA 22314 | ✓ | ✓ |  |  |  |  | 703-935-0058 |
| All Thats Therapeutic Inc | MD 20745 | ✓ | ✓ | ✓ |  |  |  | 301-567-0400 |
| Dr Goldberg and Associates PLLC — Stevenson Alexandria Office | VA 22304 | ✓ | ✓ |  |  |  |  | 703-935-0058 |
| Cornerstone Montgomery | MD 20814 | ✓ | ✓ | ✓ |  | ✓ |  | 301-493-4200 |
| Cornerstone Montgomery | MD 20902 | ✓ | ✓ | ✓ |  | ✓ |  | 301-493-4200 x2 |
| Nimel Mental Health LLC | MD 20740 | ✓ | ✓ | ✓ | ✓ | ✓ |  | 301-272-1558 |
| Dr Goldberg and Associates PLLC — McLean Office | VA 22102 | ✓ | ✓ |  |  |  |  | 703-935-0058 |
| Interdynamics Inc | MD 20785 | ✓ | ✓ | ✓ |  |  |  | 301-306-4590 x3 |
| Maryland Family Resource Inc | MD 20785 | ✓ | ✓ | ✓ |  | ✓ |  | 301-333-2980 |
| Next Step Treatment Center | MD 20785 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 410-844-3301 |
