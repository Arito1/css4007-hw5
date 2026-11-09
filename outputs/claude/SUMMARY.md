# Scenario run summary

Model: Anthropic Claude via langchain-anthropic, model=claude-opus-5-5

Command: `python -m helpdesk scenarios --model anthropic`

| Scenario | Snapshot | Route / tools per event | Final reply (start) | Tickets | Loop limit |
| --- | --- | --- | --- | --- | --- |
| S01 | normal | START → read_request → wifi_help → END | Connect to the practice campus network (GUIDE-WIFI): 1. Check that Wi-Fi is enabled and airplane mode is off. 2. Select the fictional Campus-Demo network. 3. If | - | False |
| S02 | normal | START → read_request → password_help → END | Recover access to the practice account (GUIDE-PASSWORD): 1. Open the practice sign-in screen and choose Forgot password. 2. Follow the recovery instructions sho | - | False |
| S03 | normal | START → read_request → other_help → END | I can only help with Wi-Fi and password problems in this demo. Does your problem concern Wi-Fi or a password? | - | False |
| S04 | normal | START → read_request → wifi_help → END | Connect to the practice campus network (GUIDE-WIFI): 1. Check that Wi-Fi is enabled and airplane mode is off. 2. Select the fictional Campus-Demo network. 3. If | - | False |
| S05 | normal | START → read_request → clarify_problem → END | Your message mentions both Wi-Fi and a password. Is the problem connecting to Wi-Fi, or recovering your account password? Which one should we solve first? | - | False |
| S06 | normal | demo-user-a/s06: find_instructions; demo-user-a/s06: check_service_status, prepare_ticket | Wi-Fi isn't down. The status check says: "The demo Wi-Fi service has no reported outage."  Because the service is working, I made the ticket you asked for. It's | outputs/claude/tickets/TCK-20261109-200917-35DE16.json | False |
| S07 | wifi_outage | demo-user-a/s07: check_service_status | The Wi-Fi service is **down**. There's a campus-wide outage, and no repair time is available.  You asked for a ticket only if Wi-Fi was working, so **I didn't p | - | False |
| S08 | status_unavailable | demo-user-a/s08: check_service_status | I couldn't find out whether Wi-Fi is down. The status check came back **unknown** because the demo Wi-Fi status source isn't available. That doesn't mean Wi-Fi  | - | False |
| S09 | normal | demo-user-a/s09: no tools; demo-user-a/s09: prepare_ticket | I saved your ticket as a local draft. It hasn't been sent anywhere.  - **Ticket:** TCK-20261109-200945-43E7D2 - **Problem:** Wi-Fi connection fails - **Steps yo | outputs/claude/tickets/TCK-20261109-200945-43E7D2.json | False |
| S10 | normal | demo-user-a/s10: find_instructions, check_service_status; demo-user-a/s10: no tools | So far you've told me that you: 1. Turned on Wi-Fi. 2. Forgot the saved network and tried to reconnect, which didn't work. | - | False |
| S11 | normal | demo-user-a/restart-a: save_user_preference, find_instructions; **restart** (pid 25544→13824); demo-user-a/restart-a: no tools | Біз Wi-Fi мәселесін талқыладық. Сіз Wi-Fi-ды қосып, қайта қосылып көрдіңіз, бірақ бәрібір қосыла алмадыңыз.  Мен GUIDE-WIFI нұсқаулығынан мына қадамдарды ұсынды | - | False |
| S12 | normal | demo-user-a/preference-a1: save_user_preference, find_instructions; **restart** (pid 23604→13940); demo-user-a/preference-a2: no tools | Сіз маған **қазақ тілінде** жауап беруді сұрадыңыз. Бұл сақталған соңғы тіл таңдауыңыз.  Мен мына мәселелер бойынша көмектесе аламын: - **Wi-Fi** ақауларын шешу | - | False |
| S13 | normal | demo-user-a/isolation-a: save_user_preference, find_instructions; demo-user-b/isolation-b: no tools | No, you haven't told me a preferred language, and you haven't mentioned a previous problem. Your saved preferences are empty, and there are no earlier messages  | - | False |
| S14 | recovery_outage | demo-user-a/s14: check_service_status | Yes, there's a known problem. The account recovery service is showing an **outage**, so the recovery page being down is part of that and not something wrong on  | - | False |
| D01 | normal | demo-user-a/refer-a: find_instructions, check_service_status; demo-user-a/refer-a: prepare_ticket | I've saved a ticket draft on this device. **Nothing was sent.**  - **Ticket:** TCK-20261109-201116-B07124 - **File:** `outputs/claude/tickets/TCK-20261109-20111 | outputs/claude/tickets/TCK-20261109-201116-B07124.json | False |
