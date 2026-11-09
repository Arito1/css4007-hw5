# Scenario run summary

Model: FAKE scripted model (helpdesk/fake_model.py) - not an LLM

Command: `python -m helpdesk scenarios --model fake`

| Scenario | Snapshot | Route / tools per event | Final reply (start) | Tickets | Loop limit |
| --- | --- | --- | --- | --- | --- |
| S01 | normal | START → read_request → wifi_help → END | Connect to the practice campus network (GUIDE-WIFI): 1. Check that Wi-Fi is enabled and airplane mode is off. 2. Select the fictional Campus-Demo network. 3. If | - | False |
| S02 | normal | START → read_request → password_help → END | Recover access to the practice account (GUIDE-PASSWORD): 1. Open the practice sign-in screen and choose Forgot password. 2. Follow the recovery instructions sho | - | False |
| S03 | normal | START → read_request → other_help → END | I can only help with Wi-Fi and password problems in this demo. Does your problem concern Wi-Fi or a password? | - | False |
| S04 | normal | START → read_request → wifi_help → END | Connect to the practice campus network (GUIDE-WIFI): 1. Check that Wi-Fi is enabled and airplane mode is off. 2. Select the fictional Campus-Demo network. 3. If | - | False |
| S05 | normal | START → read_request → clarify_problem → END | Your message mentions both Wi-Fi and a password. Is the problem connecting to Wi-Fi, or recovering your account password? Which one should we solve first? | - | False |
| S06 | normal | demo-user-a/s06: find_instructions; demo-user-a/s06: check_service_status, prepare_ticket | The demo status source reports Wi-Fi is operating (The demo Wi-Fi service has no reported outage.) I prepared a local ticket draft TCK-20261109-113120-4265E0 (o | outputs/fake-model/tickets/TCK-20261109-113120-4265E0.json | False |
| S07 | wifi_outage | demo-user-a/s07: check_service_status | The demo status source reports an outage of Wi-Fi: The demo Wi-Fi service is unavailable across campus. The fixture gives no repair time. Your request said to p | - | False |
| S08 | status_unavailable | demo-user-a/s08: check_service_status | I could not determine the Wi-Fi status (The demo Wi-Fi status source is unavailable.). I cannot confirm that it is operating. Would you like a ticket draft expl | - | False |
| S09 | normal | demo-user-a/s09: no tools; demo-user-a/s09: prepare_ticket | I prepared a local ticket draft TCK-20261109-113127-021F71 (outputs/fake-model/tickets/TCK-20261109-113127-021F71.json) with the steps you stated: Enabled Wi-Fi | outputs/fake-model/tickets/TCK-20261109-113127-021F71.json | False |
| S10 | normal | demo-user-a/s10: find_instructions; demo-user-a/s10: no tools | You reported a Wi-Fi problem. Steps you said you already tried: Enabled Wi-Fi; Forgot the saved network; Tried reconnecting, and it still did not work. | - | False |
| S11 | normal | demo-user-a/restart-a: save_user_preference, find_instructions; **restart** (pid 7040→20248); demo-user-a/restart-a: no tools | [Reply language from user memory: Kazakh. This FAKE model cannot translate; the real model answers in Kazakh.] You reported a Wi-Fi problem. Steps you said you  | - | False |
| S12 | normal | demo-user-a/preference-a1: save_user_preference, find_instructions; **restart** (pid 22040→21520); demo-user-a/preference-a2: no tools | [Reply language from user memory: Kazakh. This FAKE model cannot translate; the real model answers in Kazakh.] You asked me to reply in Kazakh (read from your s | - | False |
| S13 | normal | demo-user-a/isolation-a: save_user_preference, find_instructions; demo-user-b/isolation-b: no tools | No preferred language and no previous problem have been recorded for you. Tell me your problem and, if you like, the language you prefer. | - | False |
| S14 | recovery_outage | demo-user-a/s14: check_service_status | The demo status source reports an outage of account recovery: The demo account-recovery service is unavailable. The fixture gives no repair time. If you want, I | - | False |
| D01 | normal | demo-user-a/refer-a: find_instructions; demo-user-a/refer-a: no tools | "That" refers to the GUIDE-WIFI steps I gave you earlier in this conversation. Since they did not solve it, the next step is to check the service status; I can  | - | False |
