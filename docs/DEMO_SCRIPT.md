# Scheme Saathi demo script (Role 1)

**Status:** DRAFT v1 for team rehearsal. Hindi and Marathi lines are model-drafted (Copilot first draft, revised with Claude) and **must be checked by a native speaker** before the demo.
**Length:** about 9 minutes. **Data:** synthetic only. Say this at the start and keep the on-screen warning visible.
**Schemes shown live:** IGNWPS-MH (widow pension), IGNOAPS-MH (old-age pension), PM-KISAN-IN.

## 0. Setup (before the demo)
- Open the app in English. Have a Hindi tab and a Marathi tab ready.
- Persona A: widow, aged 40 today, BPL card shown (eligible). Persona B: same woman one day before her 40th birthday (not eligible). Persona C: widow aged 55, no answer about the BPL card (can't tell).
- Do not type any real name, phone number or ID.

## 1. The problem (45 s) - Role 1
**EN:** "Many families miss welfare schemes because the rules are long, differ by state, and change. Saathi helps a citizen or a CSC operator check likely eligibility, see what documents to bring, and prepare an application. A person always approves it. Everything today is synthetic."
**HI:** "कई परिवार कल्याणकारी योजनाओं का लाभ नहीं ले पाते, क्योंकि नियम लंबे होते हैं, हर राज्य में अलग होते हैं और बदलते रहते हैं। साथी नागरिक या CSC संचालक को संभावित पात्रता जाँचने, ज़रूरी दस्तावेज़ जानने और आवेदन तैयार करने में मदद करता है। आवेदन को मंज़ूरी हमेशा एक व्यक्ति देता है। आज का सारा डेटा काल्पनिक है।"
**MR:** "अनेक कुटुंबांना कल्याणकारी योजनांचा लाभ मिळत नाही, कारण नियम लांबलचक असतात, राज्यानुसार वेगळे असतात आणि बदलत राहतात. साथी नागरिकाला किंवा CSC चालकाला संभाव्य पात्रता तपासण्यास, कोणती कागदपत्रे लागतात ते जाणून घेण्यास आणि अर्ज तयार करण्यास मदत करतो. अर्जाला मंजुरी नेहमी एक व्यक्ती देते. आजचा सर्व डेटा काल्पनिक आहे."

## 2. What Saathi will not do (30 s) - Role 1 (policy)
Say: Saathi gives a screening opinion, not a guarantee; it never takes real IDs; it hands unclear cases to a caseworker. (Source: `docs/POLICY.md`.)
**HI:** "साथी पात्रता की राय देता है, गारंटी नहीं। असली पहचान-पत्र कभी नहीं लेता। अस्पष्ट मामले केसवर्कर को भेजता है।"
**MR:** "साथी पात्रतेबद्दल मत देतो, हमी नाही. खरी ओळखपत्रे कधीही घेत नाही. अस्पष्ट प्रकरणे संबंधित कर्मचाऱ्याकडे पाठवतो."

## 3. Eligible case (90 s) - Persona A
1. Choose the Maharashtra widow pension, citizen mode, give consent.
2. Saathi asks date of birth, widow status, BPL card. Answer from Persona A.
3. Point out: verdict **eligible**, the deciding rules (age 40-79, widow, BPL), the source URL and collection date.
**EN:** "Notice that Saathi cites the department page and the date it was collected."
**HI:** "देखिए, साथी विभाग के पेज का हवाला देता है और बताता है कि जानकारी किस तारीख को ली गई थी।"
**MR:** "पहा, साथी विभागाच्या वेबपेजचा संदर्भ देतो आणि माहिती कोणत्या तारखेला घेतली ते दाखवतो."

## 4. The boundary (60 s) - Persona B
1. Restart with Persona B (one day before 40).
2. Verdict **not eligible**; deciding rule: minimum age 40.
**EN:** "One day makes the difference, and Saathi explains exactly which rule decided it."
**HI:** "सिर्फ़ एक दिन से फ़ैसला बदल जाता है, और साथी ठीक-ठीक बताता है कि किस नियम से फ़ैसला हुआ।"
**MR:** "फक्त एका दिवसामुळे निर्णय बदलतो, आणि साथी नेमका कोणता नियम निर्णायक ठरला ते सांगतो."

## 5. "Can't tell" and the caseworker (60 s) - Persona C
1. Persona C does not know whether she has a BPL card.
2. Verdict **can't tell**, with the missing fact named. Saathi does not guess.
3. Show the referral to a human caseworker (policy section 2).
**EN:** "When facts are missing, it says so and refers the case."
**HI:** "जब कोई ज़रूरी जानकारी नहीं होती, तो साथी यह साफ़ बताता है और मामला केसवर्कर को भेज देता है।"
**MR:** "माहिती अपुरी असल्यास साथी तसे सांगतो आणि प्रकरण संबंधित कर्मचाऱ्याकडे पाठवतो."

## 6. Same answer in three languages (45 s)
Re-run Persona A in Hindi, then Marathi. Same verdict and same deciding rules.
**EN:** "The verdict does not change with language."
**HI:** "भाषा बदलने से फ़ैसला नहीं बदलता।"
**MR:** "भाषा बदलल्याने निर्णय बदलत नाही."

## 7. Documents and approval (120 s) - Roles 4/6 can lead
1. Show the document checklist, then the **Upload documents** tab: attach a synthetic PDF, JPG or PNG.
2. In the **Document checker** tab, type a name that differs from the profile. Show the `name_mismatch` warning, acknowledge it with a note, then reopen it.
3. Say clearly: "The checker compares name and date of birth only. It does not prove a document is genuine. A person reviews it."
4. Show the draft application. Approve it as the human. Then edit one field: the approval is **invalidated** and must be given again.
5. After submission show **Under review** and the reviewer sign-off. Do not demo the optional file-reading model live (free model, unreliable on Marathi).
**EN:** "Approval applies to the exact draft. Change one field and approval is withdrawn."
**HI:** "मंज़ूरी ठीक उसी मसौदे (ड्राफ़्ट) पर लागू होती है। कोई एक भी जानकारी बदलने पर मंज़ूरी रद्द हो जाती है।"
**MR:** "मंजुरी नेमक्या मसुद्यालाच लागू होते. एखादी माहिती बदलल्यास मंजुरी रद्द होते."

## 8. Forget and close (30 s)
Use "Forget demonstration data". Then: how we measure (development personas, held-out cases written by a different teammate), and the limits: three schemes live, others retrieval only.
**HI:** "डेमो का डेटा हटाया जा सकता है। अभी तीन योजनाएँ लाइव हैं; बाकी योजनाओं के लिए सिर्फ़ जानकारी दिखाई जाती है।"
**MR:** "डेमोचा डेटा काढता येतो. सध्या तीन योजना लाइव्ह आहेत; इतर योजनांसाठी फक्त माहिती दाखवली जाते."

## Rehearsal checklist
- [ ] Hindi and Marathi lines checked by a native speaker
- [ ] Personas A, B, C produce the stated verdicts in the running app
- [ ] The approval-invalidation step works as described
- [ ] One full run with the team, timed
- [ ] Backup recording available
