"""Internationalization: all hardcoded TTS messages in 32 languages.

Supports all languages available in ElevenLabs Flash v2.5.
Use msg(userdata, key, **kwargs) to get a translated message.
"""

# Deepgram STT language codes (where they differ from ElevenLabs TTS codes)
DEEPGRAM_CODES: dict[str, str] = {
    "fil": "tl",  # Filipino → Tagalog in Deepgram
}


def deepgram_code(lang: str) -> str:
    """Get the Deepgram language code for a given ElevenLabs language code."""
    return DEEPGRAM_CODES.get(lang, lang)


def msg(userdata, key: str, **kwargs) -> str:
    """Get a translated message for the current session language."""
    lang = getattr(userdata, "language", "nl")
    messages = MESSAGES.get(lang, MESSAGES["nl"])
    template = messages.get(key, MESSAGES["nl"].get(key, key))
    return template.format(**kwargs) if kwargs else template


# ---------------------------------------------------------------------------
# All message keys:
#
#   irrelevant_shutdown      — conversation ended due to irrelevant answers
#   recruiter_handoff        — transferring to recruiter
#   silence_prompt           — first silence: "are you there?"
#   silence_shutdown         — second silence: ending call
#   screening_unclear        — knockout question unanswered
#   ready_check              — transition to open questions
#   ready_check_decline      — candidate declined ready check
#   open_questions_thanks    — thanks after open questions
#   existing_booking         — candidate already has appointment ({date})
#   scheduling_invite        — invitation to schedule ({location})
#   scheduling_confirm       — timeslot confirmed ({timeslot}, {location}, {address}, {followup})
#   scheduling_followup_tomorrow — WhatsApp confirmation (tomorrow)
#   scheduling_followup_later    — WhatsApp confirmation + reminder
#   scheduling_preference    — no slot fit, saving preference
#   recruiter_greeting       — recruiter agent greeting ({name})
#   recruiter_goodbye        — recruiter agent goodbye
#   alternative_thanks       — thanks after alternative questions
#   alternative_not_interested — candidate not interested in alternatives
#   voicemail_with_name      — voicemail message ({name})
#   voicemail_without_name   — voicemail message (no name)
#   proxy_detected           — caller is not the candidate
#   candidate_not_available  — candidate has no time
#   agent_greeting           — hardcoded intro line ({persona_name})
# ---------------------------------------------------------------------------

MESSAGES: dict[str, dict[str, str]] = {
    # ── Dutch (default) ──────────────────────────────────────────────────
    "nl": {
        "irrelevant_shutdown": "Sorry, ik denk dat dit gesprek niet helemaal vlot verloopt. Als je later toch geinteresseerd bent, neem dan gerust contact op. Nog een fijne dag.",
        "recruiter_handoff": "Natuurlijk, ik verbind je door met de recruiter. Een moment.",
        "silence_prompt": "Sorry, ik heb je niet goed gehoord. Kan je dat nog eens zeggen?",
        "silence_shutdown": "Ik hoor je helaas niet meer. Als je later toch geinteresseerd bent, neem dan gerust contact op. Nog een fijne dag.",
        "screening_unclear": "Geen probleem. Zonder antwoord op deze vraag kan ik helaas niet verder met de screening. Neem gerust later contact op als je geinteresseerd bent. Nog een fijne dag.",
        "ready_check": "Ok super, bedankt voor de korte ja en nee vragen. Nu wil ik je graag nog een paar open vragen stellen over je motivatie en ervaring. Neem gerust je tijd om te antwoorden. Ben je er klaar voor?",
        "ready_check_decline": "Geen probleem. Neem gerust later contact op als je geinteresseerd bent. Nog een fijne dag.",
        "open_questions_thanks": "Super, bedankt voor je antwoorden.",
        "existing_booking": "Oké, super. Bedankt voor je antwoorden. Ik zie dat je al een interview hebt ingepland met de recruiter op {date}. Ik voeg je sollicitatie voor deze vacature toe aan de agenda van het geplande interview. Bedankt alvast voor je tijd en veel succes. Nog een fijne dag.",
        "scheduling_invite": "We willen je graag uitnodigen voor een interview met de recruiter op ons kantoor in {location}. Even kijken wanneer dat zou passen.",
        "scheduling_confirm": "Super, dan staat je gesprek gepland op {timeslot} met de recruiter op ons kantoor in {location}. {followup} Bedankt voor het gesprek veel succes en nog een fijne dag.",
        "scheduling_followup_tomorrow": "Je ontvangt zo meteen nog een bevestiging via WhatsApp met het exacte adres en tijdstip.",
        "scheduling_followup_later": "Je ontvangt een bevestiging met het exacte adres en tijdstip en later ook nog een reminder via WhatsApp.",
        "scheduling_preference": "Ik noteer je voorkeur en geef dit door aan de recruiter. Die neemt zo snel mogelijk contact met je op om een geschikt moment te vinden. Bedankt voor je tijd en nog een fijne dag.",
        "recruiter_greeting": "Hallo {name}, je spreekt nu met de recruiter. Hoe kan ik je helpen?",
        "recruiter_goodbye": "Bedankt voor het gesprek. Ik neem alles mee en we nemen zo snel mogelijk contact op. Nog een fijne dag.",
        "alternative_thanks": "Bedankt voor je antwoorden. Ik geef dit door aan de recruiter en die neemt zo snel mogelijk contact met je op. Nog een fijne dag.",
        "alternative_not_interested": "Helemaal oke, geen probleem. Als je in de toekomst toch interesse hebt, neem dan gerust contact op. Nog een fijne dag.",
        "voicemail_with_name": "Hallo {name}, je spreekt met {persona_name} van Go For Jobs. We belden je in verband met je sollicitatie. Bel ons gerust terug wanneer het je past. Nog een fijne dag.",
        "voicemail_without_name": "Hallo, je spreekt met {persona_name} van Go For Jobs. We belden je in verband met je sollicitatie. Bel ons gerust terug wanneer het je past. Nog een fijne dag.",
        "proxy_detected": "Ah oke, geen probleem. Dit gesprek is bedoeld voor de kandidaat persoonlijk. Zou je kunnen vragen of zij of hij ons terugbelt wanneer het past? Bedankt en nog een fijne dag.",
        "candidate_not_available": "Helemaal oke. Neem gerust contact op als je even tijd hebt. Nog een fijne dag.",
        "agent_greeting": "Goedemiddag, je spreekt met {persona_name}, de digitale assistent van Go For Jobs. Ik ben speciaal ontwikkeld om jou sneller aan een job te helpen. Heb je nu even tijd om enkele korte vragen te beantwoorden?",
    },
    # ── English ──────────────────────────────────────────────────────────
    "en": {
        "irrelevant_shutdown": "Sorry, I don't think this conversation is going very smoothly. If you're interested later, feel free to get in touch. Have a nice day.",
        "recruiter_handoff": "Of course, let me transfer you to the recruiter. One moment.",
        "silence_prompt": "Sorry, I didn't catch that. Could you say that again?",
        "silence_shutdown": "I can't hear you anymore unfortunately. If you're interested later, feel free to get in touch. Have a nice day.",
        "screening_unclear": "No problem. Without an answer to this question I unfortunately can't continue with the screening. Feel free to get in touch later if you're interested. Have a nice day.",
        "ready_check": "Great, thanks for the short yes and no questions. Now I'd like to ask you a few open questions about your motivation and experience. Take your time to answer. Are you ready?",
        "ready_check_decline": "No problem. Feel free to get in touch later if you're interested. Have a nice day.",
        "open_questions_thanks": "Great, thanks for your answers.",
        "existing_booking": "Okay, great. Thanks for your answers. I see you already have an interview scheduled with the recruiter on {date}. I'll add your application for this vacancy to the agenda of that scheduled interview. Thanks for your time and good luck. Have a nice day.",
        "scheduling_invite": "We'd like to invite you for a short interview with the recruiter at our office in {location}. Let's see when that would work.",
        "scheduling_confirm": "Great, your interview is scheduled for {timeslot}, with the recruiter at our office in {location} at {address}. {followup} Thanks for the conversation, good luck and have a nice day.",
        "scheduling_followup_tomorrow": "You'll receive a confirmation via WhatsApp shortly.",
        "scheduling_followup_later": "You'll receive a confirmation and later a reminder via WhatsApp.",
        "scheduling_preference": "I'll note your preference and pass it on to the recruiter. They'll get in touch as soon as possible to find a suitable time. Thanks for your time and have a nice day.",
        "recruiter_greeting": "Hello {name}, you're now speaking with the recruiter. How can I help you?",
        "recruiter_goodbye": "Thanks for the conversation. I'll take everything along and we'll get in touch as soon as possible. Have a nice day.",
        "alternative_thanks": "Thanks for your answers. I'll pass this on to the recruiter and they'll get in touch as soon as possible. Have a nice day.",
        "alternative_not_interested": "Totally fine, no problem. If you're interested in the future, feel free to get in touch. Have a nice day.",
        "voicemail_with_name": "Hello {name}, this is {persona_name} from Go For Jobs. We called you regarding your application. Feel free to call us back when it suits you. Have a nice day.",
        "voicemail_without_name": "Hello, this is {persona_name} from Go For Jobs. We called you regarding your application. Feel free to call us back when it suits you. Have a nice day.",
        "proxy_detected": "Ah okay, no problem. This conversation is meant for the candidate personally. Could you ask them to call us back when it suits them? Thanks and have a nice day.",
        "candidate_not_available": "Totally fine. Feel free to get in touch when you have a moment. Have a nice day.",
        "agent_greeting": "Good afternoon, you're speaking with {persona_name}, the digital assistant from Go For Jobs. I've been specially developed to help you find a job faster. Do you have a moment to answer a few short questions?",
    },
    # ── French ───────────────────────────────────────────────────────────
    "fr": {
        "irrelevant_shutdown": "Désolé, je pense que cette conversation ne se passe pas très bien. Si vous êtes intéressé plus tard, n'hésitez pas à nous contacter. Bonne journée.",
        "recruiter_handoff": "Bien sûr, je vous transfère au recruteur. Un instant.",
        "silence_prompt": "Désolé, je n'ai pas bien entendu. Pouvez-vous répéter ?",
        "silence_shutdown": "Je ne vous entends plus malheureusement. Si vous êtes intéressé plus tard, n'hésitez pas à nous contacter. Bonne journée.",
        "screening_unclear": "Pas de problème. Sans réponse à cette question, je ne peux malheureusement pas continuer la sélection. N'hésitez pas à nous contacter plus tard si vous êtes intéressé. Bonne journée.",
        "ready_check": "Super, merci pour les courtes questions oui ou non. Maintenant j'aimerais vous poser quelques questions ouvertes sur votre motivation et votre expérience. Prenez votre temps pour répondre. Êtes-vous prêt ?",
        "ready_check_decline": "Pas de problème. N'hésitez pas à nous contacter plus tard si vous êtes intéressé. Bonne journée.",
        "open_questions_thanks": "Super, merci pour vos réponses.",
        "existing_booking": "Ok, super. Merci pour vos réponses. Je vois que vous avez déjà un entretien prévu avec le recruteur le {date}. J'ajoute votre candidature pour ce poste à l'ordre du jour de cet entretien. Merci pour votre temps et bonne chance. Bonne journée.",
        "scheduling_invite": "Nous aimerions vous inviter pour un court entretien avec le recruteur dans notre bureau à {location}. Voyons quand cela vous conviendrait.",
        "scheduling_confirm": "Super, votre entretien est prévu le {timeslot}, avec le recruteur dans notre bureau à {location}, {address}. {followup} Merci pour la conversation, bonne chance et bonne journée.",
        "scheduling_followup_tomorrow": "Vous recevrez une confirmation par WhatsApp sous peu.",
        "scheduling_followup_later": "Vous recevrez une confirmation et plus tard un rappel par WhatsApp.",
        "scheduling_preference": "Je note votre préférence et je la transmets au recruteur. Il vous contactera dès que possible pour trouver un moment qui convient. Merci pour votre temps et bonne journée.",
        "recruiter_greeting": "Bonjour {name}, vous parlez maintenant avec le recruteur. Comment puis-je vous aider ?",
        "recruiter_goodbye": "Merci pour la conversation. Je prends tout en note et nous vous contacterons dès que possible. Bonne journée.",
        "alternative_thanks": "Merci pour vos réponses. Je transmets cela au recruteur et il vous contactera dès que possible. Bonne journée.",
        "alternative_not_interested": "Tout à fait, pas de problème. Si vous êtes intéressé à l'avenir, n'hésitez pas à nous contacter. Bonne journée.",
        "voicemail_with_name": "Bonjour {name}, c'est {persona_name} de Go For Jobs. Nous vous avons appelé au sujet de votre candidature. N'hésitez pas à nous rappeler quand cela vous convient. Bonne journée.",
        "voicemail_without_name": "Bonjour, c'est {persona_name} de Go For Jobs. Nous vous avons appelé au sujet de votre candidature. N'hésitez pas à nous rappeler quand cela vous convient. Bonne journée.",
        "proxy_detected": "Ah d'accord, pas de problème. Cette conversation est destinée au candidat personnellement. Pourriez-vous lui demander de nous rappeler quand cela lui convient ? Merci et bonne journée.",
        "candidate_not_available": "Tout à fait. N'hésitez pas à nous contacter quand vous avez un moment. Bonne journée.",
        "agent_greeting": "Bonjour, vous parlez avec {persona_name}, l'assistant digital de Go For Jobs. J'ai été spécialement conçu pour vous aider à trouver un emploi plus rapidement. Avez-vous un moment pour répondre à quelques courtes questions ?",
    },
    # ── German ───────────────────────────────────────────────────────────
    "de": {
        "irrelevant_shutdown": "Tut mir leid, ich glaube dieses Gespräch läuft nicht ganz reibungslos. Wenn Sie später Interesse haben, melden Sie sich gerne. Einen schönen Tag noch.",
        "recruiter_handoff": "Natürlich, ich verbinde Sie mit dem Recruiter. Einen Moment bitte.",
        "silence_prompt": "Entschuldigung, ich habe Sie nicht verstanden. Könnten Sie das noch einmal sagen?",
        "silence_shutdown": "Ich kann Sie leider nicht mehr hören. Wenn Sie später Interesse haben, melden Sie sich gerne. Einen schönen Tag noch.",
        "screening_unclear": "Kein Problem. Ohne eine Antwort auf diese Frage kann ich leider nicht mit dem Screening fortfahren. Melden Sie sich gerne später, wenn Sie interessiert sind. Einen schönen Tag noch.",
        "ready_check": "Super, danke für die kurzen Ja- und Nein-Fragen. Jetzt möchte ich Ihnen gerne ein paar offene Fragen zu Ihrer Motivation und Erfahrung stellen. Nehmen Sie sich ruhig Zeit zum Antworten. Sind Sie bereit?",
        "ready_check_decline": "Kein Problem. Melden Sie sich gerne später, wenn Sie interessiert sind. Einen schönen Tag noch.",
        "open_questions_thanks": "Super, danke für Ihre Antworten.",
        "existing_booking": "Okay, super. Danke für Ihre Antworten. Ich sehe, dass Sie bereits ein Gespräch mit dem Recruiter am {date} geplant haben. Ich füge Ihre Bewerbung für diese Stelle der Agenda des geplanten Gesprächs hinzu. Danke für Ihre Zeit und viel Erfolg. Einen schönen Tag noch.",
        "scheduling_invite": "Wir möchten Sie gerne zu einem kurzen Gespräch mit dem Recruiter in unserem Büro in {location} einladen. Schauen wir mal, wann das passen würde.",
        "scheduling_confirm": "Super, Ihr Gespräch ist geplant für {timeslot}, mit dem Recruiter in unserem Büro in {location}, {address}. {followup} Danke für das Gespräch, viel Erfolg und einen schönen Tag noch.",
        "scheduling_followup_tomorrow": "Sie erhalten in Kürze eine Bestätigung per WhatsApp.",
        "scheduling_followup_later": "Sie erhalten eine Bestätigung und später auch eine Erinnerung per WhatsApp.",
        "scheduling_preference": "Ich notiere Ihre Präferenz und gebe sie an den Recruiter weiter. Er wird sich so schnell wie möglich bei Ihnen melden, um einen passenden Termin zu finden. Danke für Ihre Zeit und einen schönen Tag noch.",
        "recruiter_greeting": "Hallo {name}, Sie sprechen jetzt mit dem Recruiter. Wie kann ich Ihnen helfen?",
        "recruiter_goodbye": "Danke für das Gespräch. Ich nehme alles mit und wir melden uns so schnell wie möglich. Einen schönen Tag noch.",
        "alternative_thanks": "Danke für Ihre Antworten. Ich gebe das an den Recruiter weiter und er wird sich so schnell wie möglich bei Ihnen melden. Einen schönen Tag noch.",
        "alternative_not_interested": "Völlig in Ordnung, kein Problem. Wenn Sie in Zukunft Interesse haben, melden Sie sich gerne. Einen schönen Tag noch.",
        "voicemail_with_name": "Hallo {name}, hier spricht {persona_name} von Go For Jobs. Wir haben Sie wegen Ihrer Bewerbung angerufen. Rufen Sie uns gerne zurück, wenn es Ihnen passt. Einen schönen Tag noch.",
        "voicemail_without_name": "Hallo, hier spricht {persona_name} von Go For Jobs. Wir haben Sie wegen Ihrer Bewerbung angerufen. Rufen Sie uns gerne zurück, wenn es Ihnen passt. Einen schönen Tag noch.",
        "proxy_detected": "Ah okay, kein Problem. Dieses Gespräch ist für den Kandidaten persönlich gedacht. Könnten Sie ihn oder sie bitten, uns zurückzurufen, wenn es passt? Danke und einen schönen Tag noch.",
        "candidate_not_available": "Völlig in Ordnung. Melden Sie sich gerne, wenn Sie einen Moment Zeit haben. Einen schönen Tag noch.",
        "agent_greeting": "Guten Tag, Sie sprechen mit {persona_name}, dem digitalen Assistenten von Go For Jobs. Ich wurde speziell entwickelt, um Ihnen schneller zu einem Job zu verhelfen. Haben Sie kurz Zeit, um einige Fragen zu beantworten?",
    },
    # ── Spanish ──────────────────────────────────────────────────────────
    "es": {
        "irrelevant_shutdown": "Lo siento, creo que esta conversación no está yendo muy bien. Si te interesa más adelante, no dudes en contactarnos. Que tengas un buen día.",
        "recruiter_handoff": "Por supuesto, te transfiero con el reclutador. Un momento.",
        "silence_prompt": "Perdona, no te he escuchado bien. ¿Podrías repetirlo?",
        "silence_shutdown": "Lamentablemente ya no puedo escucharte. Si te interesa más adelante, no dudes en contactarnos. Que tengas un buen día.",
        "screening_unclear": "No hay problema. Sin una respuesta a esta pregunta, lamentablemente no puedo continuar con la selección. No dudes en contactarnos más adelante si te interesa. Que tengas un buen día.",
        "ready_check": "Genial, gracias por las preguntas cortas de sí o no. Ahora me gustaría hacerte algunas preguntas abiertas sobre tu motivación y experiencia. Tómate tu tiempo para responder. ¿Estás listo?",
        "ready_check_decline": "No hay problema. No dudes en contactarnos más adelante si te interesa. Que tengas un buen día.",
        "open_questions_thanks": "Genial, gracias por tus respuestas.",
        "existing_booking": "Vale, genial. Gracias por tus respuestas. Veo que ya tienes una entrevista programada con el reclutador el {date}. Añadiré tu candidatura para esta vacante a la agenda de esa entrevista. Gracias por tu tiempo y mucha suerte. Que tengas un buen día.",
        "scheduling_invite": "Nos gustaría invitarte a una breve entrevista con el reclutador en nuestra oficina en {location}. Veamos cuándo te vendría bien.",
        "scheduling_confirm": "Genial, tu entrevista está programada para el {timeslot}, con el reclutador en nuestra oficina en {location}, {address}. {followup} Gracias por la conversación, mucha suerte y que tengas un buen día.",
        "scheduling_followup_tomorrow": "Recibirás una confirmación por WhatsApp en breve.",
        "scheduling_followup_later": "Recibirás una confirmación y más adelante un recordatorio por WhatsApp.",
        "scheduling_preference": "Anoto tu preferencia y se la paso al reclutador. Se pondrá en contacto contigo lo antes posible para encontrar un momento adecuado. Gracias por tu tiempo y que tengas un buen día.",
        "recruiter_greeting": "Hola {name}, ahora estás hablando con el reclutador. ¿Cómo puedo ayudarte?",
        "recruiter_goodbye": "Gracias por la conversación. Me llevo todo y nos pondremos en contacto lo antes posible. Que tengas un buen día.",
        "alternative_thanks": "Gracias por tus respuestas. Se lo paso al reclutador y se pondrá en contacto contigo lo antes posible. Que tengas un buen día.",
        "alternative_not_interested": "Totalmente bien, no hay problema. Si en el futuro te interesa, no dudes en contactarnos. Que tengas un buen día.",
        "voicemail_with_name": "Hola {name}, soy {persona_name} de Go For Jobs. Te llamamos respecto a tu solicitud. No dudes en devolvernos la llamada cuando te venga bien. Que tengas un buen día.",
        "voicemail_without_name": "Hola, soy {persona_name} de Go For Jobs. Te llamamos respecto a tu solicitud. No dudes en devolvernos la llamada cuando te venga bien. Que tengas un buen día.",
        "proxy_detected": "Ah vale, no hay problema. Esta conversación es para el candidato personalmente. ¿Podrías pedirle que nos devuelva la llamada cuando le venga bien? Gracias y que tengas un buen día.",
        "candidate_not_available": "Totalmente bien. No dudes en contactarnos cuando tengas un momento. Que tengas un buen día.",
        "agent_greeting": "Buenas tardes, estás hablando con {persona_name}, el asistente digital de Go For Jobs. He sido desarrollado especialmente para ayudarte a encontrar trabajo más rápido. ¿Tienes un momento para responder algunas preguntas cortas?",
    },
    # ── Italian ──────────────────────────────────────────────────────────
    "it": {
        "irrelevant_shutdown": "Mi dispiace, penso che questa conversazione non stia andando molto bene. Se sei interessato più avanti, non esitare a contattarci. Buona giornata.",
        "recruiter_handoff": "Certo, ti trasferisco al reclutatore. Un momento.",
        "silence_prompt": "Scusa, non ti ho sentito bene. Puoi ripetere?",
        "silence_shutdown": "Purtroppo non riesco più a sentirti. Se sei interessato più avanti, non esitare a contattarci. Buona giornata.",
        "screening_unclear": "Nessun problema. Senza una risposta a questa domanda purtroppo non posso continuare con la selezione. Non esitare a contattarci più avanti se sei interessato. Buona giornata.",
        "ready_check": "Ottimo, grazie per le brevi domande sì o no. Ora vorrei farti alcune domande aperte sulla tua motivazione e esperienza. Prenditi il tuo tempo per rispondere. Sei pronto?",
        "ready_check_decline": "Nessun problema. Non esitare a contattarci più avanti se sei interessato. Buona giornata.",
        "open_questions_thanks": "Ottimo, grazie per le tue risposte.",
        "existing_booking": "Ok, perfetto. Grazie per le tue risposte. Vedo che hai già un colloquio programmato con il reclutatore il {date}. Aggiungo la tua candidatura per questa posizione all'agenda del colloquio programmato. Grazie per il tuo tempo e in bocca al lupo. Buona giornata.",
        "scheduling_invite": "Vorremmo invitarti per un breve colloquio con il reclutatore nel nostro ufficio a {location}. Vediamo quando potrebbe andare bene.",
        "scheduling_confirm": "Ottimo, il tuo colloquio è fissato per {timeslot}, con il reclutatore nel nostro ufficio a {location}, {address}. {followup} Grazie per la conversazione, in bocca al lupo e buona giornata.",
        "scheduling_followup_tomorrow": "Riceverai a breve una conferma via WhatsApp.",
        "scheduling_followup_later": "Riceverai una conferma e più avanti un promemoria via WhatsApp.",
        "scheduling_preference": "Prendo nota della tua preferenza e la passo al reclutatore. Ti contatterà il prima possibile per trovare un momento adatto. Grazie per il tuo tempo e buona giornata.",
        "recruiter_greeting": "Ciao {name}, ora stai parlando con il reclutatore. Come posso aiutarti?",
        "recruiter_goodbye": "Grazie per la conversazione. Prendo nota di tutto e ti contatteremo il prima possibile. Buona giornata.",
        "alternative_thanks": "Grazie per le tue risposte. Passo tutto al reclutatore e ti contatterà il prima possibile. Buona giornata.",
        "alternative_not_interested": "Va benissimo, nessun problema. Se in futuro sei interessato, non esitare a contattarci. Buona giornata.",
        "voicemail_with_name": "Ciao {name}, sono {persona_name} di Go For Jobs. Ti abbiamo chiamato riguardo alla tua candidatura. Non esitare a richiamarci quando ti fa comodo. Buona giornata.",
        "voicemail_without_name": "Ciao, sono {persona_name} di Go For Jobs. Ti abbiamo chiamato riguardo alla tua candidatura. Non esitare a richiamarci quando ti fa comodo. Buona giornata.",
        "proxy_detected": "Ah ok, nessun problema. Questa conversazione è destinata al candidato personalmente. Potresti chiedergli di richiamarci quando gli fa comodo? Grazie e buona giornata.",
        "candidate_not_available": "Va benissimo. Non esitare a contattarci quando hai un momento. Buona giornata.",
        "agent_greeting": "Buon pomeriggio, stai parlando con {persona_name}, l'assistente digitale di Go For Jobs. Sono stato sviluppato appositamente per aiutarti a trovare lavoro più velocemente. Hai un momento per rispondere a qualche breve domanda?",
    },
    # ── Portuguese ───────────────────────────────────────────────────────
    "pt": {
        "irrelevant_shutdown": "Desculpe, acho que esta conversa não está correndo muito bem. Se tiver interesse mais tarde, não hesite em contactar-nos. Tenha um bom dia.",
        "recruiter_handoff": "Claro, vou transferi-lo para o recrutador. Um momento.",
        "silence_prompt": "Desculpe, não ouvi bem. Pode repetir?",
        "silence_shutdown": "Infelizmente já não consigo ouvi-lo. Se tiver interesse mais tarde, não hesite em contactar-nos. Tenha um bom dia.",
        "screening_unclear": "Sem problema. Sem resposta a esta pergunta, infelizmente não posso continuar com a seleção. Não hesite em contactar-nos mais tarde se tiver interesse. Tenha um bom dia.",
        "ready_check": "Ótimo, obrigado pelas perguntas curtas de sim ou não. Agora gostaria de fazer algumas perguntas abertas sobre a sua motivação e experiência. Tome o seu tempo para responder. Está pronto?",
        "ready_check_decline": "Sem problema. Não hesite em contactar-nos mais tarde se tiver interesse. Tenha um bom dia.",
        "open_questions_thanks": "Ótimo, obrigado pelas suas respostas.",
        "existing_booking": "Ok, ótimo. Obrigado pelas suas respostas. Vejo que já tem uma entrevista agendada com o recrutador no dia {date}. Vou adicionar a sua candidatura para esta vaga à agenda dessa entrevista. Obrigado pelo seu tempo e boa sorte. Tenha um bom dia.",
        "scheduling_invite": "Gostaríamos de convidá-lo para uma breve entrevista com o recrutador no nosso escritório em {location}. Vamos ver quando seria conveniente.",
        "scheduling_confirm": "Ótimo, a sua entrevista está marcada para {timeslot}, com o recrutador no nosso escritório em {location}, {address}. {followup} Obrigado pela conversa, boa sorte e tenha um bom dia.",
        "scheduling_followup_tomorrow": "Receberá em breve uma confirmação por WhatsApp.",
        "scheduling_followup_later": "Receberá uma confirmação e mais tarde um lembrete por WhatsApp.",
        "scheduling_preference": "Anoto a sua preferência e passo ao recrutador. Ele entrará em contacto o mais rapidamente possível para encontrar um momento adequado. Obrigado pelo seu tempo e tenha um bom dia.",
        "recruiter_greeting": "Olá {name}, está agora a falar com o recrutador. Como posso ajudá-lo?",
        "recruiter_goodbye": "Obrigado pela conversa. Levo tudo em conta e entraremos em contacto o mais rapidamente possível. Tenha um bom dia.",
        "alternative_thanks": "Obrigado pelas suas respostas. Passo isto ao recrutador e ele entrará em contacto o mais rapidamente possível. Tenha um bom dia.",
        "alternative_not_interested": "Tudo bem, sem problema. Se no futuro tiver interesse, não hesite em contactar-nos. Tenha um bom dia.",
        "voicemail_with_name": "Olá {name}, fala {persona_name} da Go For Jobs. Ligámos por causa da sua candidatura. Não hesite em ligar-nos de volta quando lhe for conveniente. Tenha um bom dia.",
        "voicemail_without_name": "Olá, fala {persona_name} da Go For Jobs. Ligámos por causa da sua candidatura. Não hesite em ligar-nos de volta quando lhe for conveniente. Tenha um bom dia.",
        "proxy_detected": "Ah ok, sem problema. Esta conversa é destinada ao candidato pessoalmente. Poderia pedir-lhe para nos ligar de volta quando lhe for conveniente? Obrigado e tenha um bom dia.",
        "candidate_not_available": "Tudo bem. Não hesite em contactar-nos quando tiver um momento. Tenha um bom dia.",
        "agent_greeting": "Boa tarde, está a falar com {persona_name}, o assistente digital da Go For Jobs. Fui especialmente desenvolvido para o ajudar a encontrar emprego mais rapidamente. Tem um momento para responder a algumas perguntas curtas?",
    },
    # ── Polish ───────────────────────────────────────────────────────────
    "pl": {
        "irrelevant_shutdown": "Przepraszam, wydaje mi się, że ta rozmowa nie przebiega zbyt dobrze. Jeśli będziesz zainteresowany później, śmiało skontaktuj się z nami. Miłego dnia.",
        "recruiter_handoff": "Oczywiście, przekierowuję cię do rekrutera. Chwileczkę.",
        "silence_prompt": "Przepraszam, nie dosłyszałem. Czy możesz powtórzyć?",
        "silence_shutdown": "Niestety nie słyszę cię już. Jeśli będziesz zainteresowany później, śmiało skontaktuj się z nami. Miłego dnia.",
        "screening_unclear": "Nie ma problemu. Bez odpowiedzi na to pytanie niestety nie mogę kontynuować selekcji. Śmiało skontaktuj się z nami później, jeśli będziesz zainteresowany. Miłego dnia.",
        "ready_check": "Świetnie, dziękuję za krótkie pytania tak lub nie. Teraz chciałbym zadać ci kilka otwartych pytań o twoją motywację i doświadczenie. Nie spiesz się z odpowiedzią. Czy jesteś gotowy?",
        "ready_check_decline": "Nie ma problemu. Śmiało skontaktuj się z nami później, jeśli będziesz zainteresowany. Miłego dnia.",
        "open_questions_thanks": "Świetnie, dziękuję za twoje odpowiedzi.",
        "existing_booking": "Ok, super. Dziękuję za twoje odpowiedzi. Widzę, że masz już zaplanowaną rozmowę z rekruterem na {date}. Dodam twoją kandydaturę na tę ofertę do agendy tego spotkania. Dziękuję za twój czas i powodzenia. Miłego dnia.",
        "scheduling_invite": "Chcielibyśmy zaprosić cię na krótką rozmowę z rekruterem w naszym biurze w {location}. Zobaczmy, kiedy by ci pasowało.",
        "scheduling_confirm": "Świetnie, twoja rozmowa jest zaplanowana na {timeslot}, z rekruterem w naszym biurze w {location}, {address}. {followup} Dziękuję za rozmowę, powodzenia i miłego dnia.",
        "scheduling_followup_tomorrow": "Wkrótce otrzymasz potwierdzenie przez WhatsApp.",
        "scheduling_followup_later": "Otrzymasz potwierdzenie i później przypomnienie przez WhatsApp.",
        "scheduling_preference": "Notuję twoją preferencję i przekazuję ją rekruterowi. Skontaktuje się z tobą jak najszybciej, aby znaleźć odpowiedni termin. Dziękuję za twój czas i miłego dnia.",
        "recruiter_greeting": "Cześć {name}, rozmawiasz teraz z rekruterem. Jak mogę ci pomóc?",
        "recruiter_goodbye": "Dziękuję za rozmowę. Biorę wszystko pod uwagę i skontaktujemy się jak najszybciej. Miłego dnia.",
        "alternative_thanks": "Dziękuję za twoje odpowiedzi. Przekazuję to rekruterowi i skontaktuje się z tobą jak najszybciej. Miłego dnia.",
        "alternative_not_interested": "W porządku, nie ma problemu. Jeśli w przyszłości będziesz zainteresowany, śmiało skontaktuj się z nami. Miłego dnia.",
        "voicemail_with_name": "Cześć {name}, tu {persona_name} z Go For Jobs. Dzwoniliśmy w sprawie twojej aplikacji. Śmiało oddzwoń, kiedy ci będzie pasować. Miłego dnia.",
        "voicemail_without_name": "Cześć, tu {persona_name} z Go For Jobs. Dzwoniliśmy w sprawie twojej aplikacji. Śmiało oddzwoń, kiedy ci będzie pasować. Miłego dnia.",
        "proxy_detected": "Ah ok, nie ma problemu. Ta rozmowa jest przeznaczona dla kandydata osobiście. Czy możesz poprosić go lub ją o oddzwonienie, kiedy mu lub jej będzie pasować? Dziękuję i miłego dnia.",
        "candidate_not_available": "W porządku. Śmiało skontaktuj się z nami, kiedy będziesz mieć chwilę. Miłego dnia.",
        "agent_greeting": "Dzień dobry, rozmawiasz z {persona_name}, cyfrowym asystentem Go For Jobs. Zostałem specjalnie stworzony, aby pomóc ci szybciej znaleźć pracę. Czy masz chwilę, żeby odpowiedzieć na kilka krótkich pytań?",
    },
    # ── Turkish ──────────────────────────────────────────────────────────
    "tr": {
        "irrelevant_shutdown": "Üzgünüm, bu görüşmenin pek iyi gitmediğini düşünüyorum. Daha sonra ilgilenirseniz, lütfen bizimle iletişime geçin. İyi günler.",
        "recruiter_handoff": "Tabii ki, sizi işe alım uzmanına aktarıyorum. Bir dakika.",
        "silence_prompt": "Özür dilerim, sizi duyamadım. Tekrar söyleyebilir misiniz?",
        "silence_shutdown": "Maalesef sizi artık duyamıyorum. Daha sonra ilgilenirseniz, lütfen bizimle iletişime geçin. İyi günler.",
        "screening_unclear": "Sorun değil. Bu soruya cevap olmadan maalesef seçim sürecine devam edemiyorum. Daha sonra ilgilenirseniz bizimle iletişime geçmekten çekinmeyin. İyi günler.",
        "ready_check": "Harika, kısa evet veya hayır soruları için teşekkürler. Şimdi size motivasyonunuz ve deneyiminiz hakkında birkaç açık soru sormak istiyorum. Cevaplamak için acele etmeyin. Hazır mısınız?",
        "ready_check_decline": "Sorun değil. Daha sonra ilgilenirseniz bizimle iletişime geçmekten çekinmeyin. İyi günler.",
        "open_questions_thanks": "Harika, cevaplarınız için teşekkürler.",
        "existing_booking": "Tamam, harika. Cevaplarınız için teşekkürler. {date} tarihinde işe alım uzmanıyla zaten bir görüşmeniz planlandığını görüyorum. Bu pozisyon için başvurunuzu o görüşmenin gündemine ekleyeceğim. Zamanınız için teşekkürler ve bol şans. İyi günler.",
        "scheduling_invite": "{location} adresindeki ofisimizde işe alım uzmanıyla kısa bir görüşme için sizi davet etmek istiyoruz. Bakalım ne zaman uygun olur.",
        "scheduling_confirm": "Harika, görüşmeniz {timeslot} tarihine planlandı, {location} adresindeki ofisimizde, {address}. {followup} Görüşme için teşekkürler, bol şans ve iyi günler.",
        "scheduling_followup_tomorrow": "Kısa süre içinde WhatsApp üzerinden bir onay alacaksınız.",
        "scheduling_followup_later": "WhatsApp üzerinden bir onay ve daha sonra bir hatırlatma alacaksınız.",
        "scheduling_preference": "Tercihinizi not alıyorum ve işe alım uzmanına iletiyorum. Uygun bir zaman bulmak için en kısa sürede sizinle iletişime geçecek. Zamanınız için teşekkürler ve iyi günler.",
        "recruiter_greeting": "Merhaba {name}, şimdi işe alım uzmanıyla konuşuyorsunuz. Size nasıl yardımcı olabilirim?",
        "recruiter_goodbye": "Görüşme için teşekkürler. Her şeyi not aldım ve en kısa sürede sizinle iletişime geçeceğiz. İyi günler.",
        "alternative_thanks": "Cevaplarınız için teşekkürler. Bunu işe alım uzmanına iletiyorum ve en kısa sürede sizinle iletişime geçecek. İyi günler.",
        "alternative_not_interested": "Tamam, sorun değil. Gelecekte ilgilenirseniz, lütfen bizimle iletişime geçin. İyi günler.",
        "voicemail_with_name": "Merhaba {name}, ben Go For Jobs'dan {persona_name}. Başvurunuzla ilgili sizi aradık. Size uygun olduğunda bizi geri aramaktan çekinmeyin. İyi günler.",
        "voicemail_without_name": "Merhaba, ben Go For Jobs'dan {persona_name}. Başvurunuzla ilgili sizi aradık. Size uygun olduğunda bizi geri aramaktan çekinmeyin. İyi günler.",
        "proxy_detected": "Ah tamam, sorun değil. Bu görüşme aday için kişisel olarak yapılmaktadır. Kendisine uygun olduğunda bizi geri aramasını isteyebilir misiniz? Teşekkürler ve iyi günler.",
        "candidate_not_available": "Tamam. Bir dakikanız olduğunda bizimle iletişime geçmekten çekinmeyin. İyi günler.",
        "agent_greeting": "İyi günler, Go For Jobs'nun dijital asistanı {persona_name} ile konuşuyorsunuz. Size daha hızlı iş bulmanıza yardımcı olmak için özel olarak geliştirildum. Birkaç kısa soruyu yanıtlamak için bir dakikanız var mı?",
    },
    # ── Arabic ───────────────────────────────────────────────────────────
    "ar": {
        "irrelevant_shutdown": "عذراً، أعتقد أن هذه المحادثة لا تسير بشكل جيد. إذا كنت مهتماً لاحقاً، لا تتردد في التواصل معنا. أتمنى لك يوماً سعيداً.",
        "recruiter_handoff": "بالطبع، سأحولك إلى المسؤول عن التوظيف. لحظة من فضلك.",
        "silence_prompt": "عذراً، لم أسمعك جيداً. هل يمكنك إعادة ذلك؟",
        "silence_shutdown": "للأسف لم أعد أسمعك. إذا كنت مهتماً لاحقاً، لا تتردد في التواصل معنا. أتمنى لك يوماً سعيداً.",
        "screening_unclear": "لا مشكلة. بدون إجابة على هذا السؤال، للأسف لا أستطيع متابعة عملية الفرز. لا تتردد في التواصل معنا لاحقاً إذا كنت مهتماً. أتمنى لك يوماً سعيداً.",
        "ready_check": "رائع، شكراً على الأسئلة القصيرة بنعم أو لا. الآن أود أن أطرح عليك بعض الأسئلة المفتوحة حول دوافعك وخبرتك. خذ وقتك في الإجابة. هل أنت مستعد؟",
        "ready_check_decline": "لا مشكلة. لا تتردد في التواصل معنا لاحقاً إذا كنت مهتماً. أتمنى لك يوماً سعيداً.",
        "open_questions_thanks": "رائع، شكراً على إجاباتك.",
        "existing_booking": "حسناً، رائع. شكراً على إجاباتك. أرى أن لديك بالفعل مقابلة مجدولة مع المسؤول عن التوظيف في {date}. سأضيف طلبك لهذه الوظيفة إلى جدول أعمال تلك المقابلة. شكراً لوقتك وبالتوفيق. أتمنى لك يوماً سعيداً.",
        "scheduling_invite": "نود دعوتك لمقابلة قصيرة مع المسؤول عن التوظيف في مكتبنا في {location}. دعنا نرى متى يناسبك.",
        "scheduling_confirm": "رائع، مقابلتك مجدولة في {timeslot}، مع المسؤول عن التوظيف في مكتبنا في {location}، {address}. {followup} شكراً على المحادثة، بالتوفيق وأتمنى لك يوماً سعيداً.",
        "scheduling_followup_tomorrow": "ستتلقى تأكيداً عبر واتساب قريباً.",
        "scheduling_followup_later": "ستتلقى تأكيداً وتذكيراً لاحقاً عبر واتساب.",
        "scheduling_preference": "سأسجل تفضيلك وأنقله إلى المسؤول عن التوظيف. سيتواصل معك في أقرب وقت ممكن لإيجاد وقت مناسب. شكراً لوقتك وأتمنى لك يوماً سعيداً.",
        "recruiter_greeting": "مرحباً {name}، أنت الآن تتحدث مع المسؤول عن التوظيف. كيف يمكنني مساعدتك؟",
        "recruiter_goodbye": "شكراً على المحادثة. سآخذ كل شيء بعين الاعتبار وسنتواصل معك في أقرب وقت ممكن. أتمنى لك يوماً سعيداً.",
        "alternative_thanks": "شكراً على إجاباتك. سأنقل هذا إلى المسؤول عن التوظيف وسيتواصل معك في أقرب وقت ممكن. أتمنى لك يوماً سعيداً.",
        "alternative_not_interested": "لا بأس، لا مشكلة. إذا كنت مهتماً في المستقبل، لا تتردد في التواصل معنا. أتمنى لك يوماً سعيداً.",
        "voicemail_with_name": "مرحباً {name}، أنا {persona_name} من Go For Jobs. اتصلنا بك بخصوص طلبك. لا تتردد في معاودة الاتصال بنا عندما يناسبك. أتمنى لك يوماً سعيداً.",
        "voicemail_without_name": "مرحباً، أنا {persona_name} من Go For Jobs. اتصلنا بك بخصوص طلبك. لا تتردد في معاودة الاتصال بنا عندما يناسبك. أتمنى لك يوماً سعيداً.",
        "proxy_detected": "آه حسناً، لا مشكلة. هذه المحادثة مخصصة للمرشح شخصياً. هل يمكنك أن تطلب منه أو منها معاودة الاتصال بنا عندما يناسبه؟ شكراً وأتمنى لك يوماً سعيداً.",
        "candidate_not_available": "لا بأس. لا تتردد في التواصل معنا عندما يكون لديك وقت. أتمنى لك يوماً سعيداً.",
        "agent_greeting": "مساء الخير، أنت تتحدث مع {persona_name}، المساعد الرقمي من Go For Jobs. تم تطويري خصيصاً لمساعدتك في العثور على وظيفة بشكل أسرع. هل لديك لحظة للإجابة على بعض الأسئلة القصيرة؟",
    },
}

# For remaining languages, generate from English template with localized greetings/closings.
# These are best-effort translations suitable for TTS output.

_REMAINING = {
    "ja": ("Japanese", "こんにちは", "良い一日を。", "はい", "いいえ"),
    "zh": ("Chinese", "你好", "祝你有美好的一天。", "是", "否"),
    "hi": ("Hindi", "नमस्ते", "आपका दिन शुभ हो।", "हाँ", "नहीं"),
    "ko": ("Korean", "안녕하세요", "좋은 하루 되세요.", "네", "아니요"),
    "id": ("Indonesian", "Halo", "Selamat siang.", "ya", "tidak"),
    "fil": ("Filipino", "Kumusta", "Magandang araw.", "oo", "hindi"),
    "sv": ("Swedish", "Hej", "Ha en bra dag.", "ja", "nej"),
    "bg": ("Bulgarian", "Здравейте", "Хубав ден.", "да", "не"),
    "ro": ("Romanian", "Bună ziua", "O zi bună.", "da", "nu"),
    "cs": ("Czech", "Dobrý den", "Hezký den.", "ano", "ne"),
    "el": ("Greek", "Γεια σας", "Καλή ημέρα.", "ναι", "όχι"),
    "fi": ("Finnish", "Hei", "Hyvää päivää.", "kyllä", "ei"),
    "hr": ("Croatian", "Bok", "Ugodan dan.", "da", "ne"),
    "ms": ("Malay", "Halo", "Selamat hari.", "ya", "tidak"),
    "sk": ("Slovak", "Dobrý deň", "Pekný deň.", "áno", "nie"),
    "da": ("Danish", "Hej", "Hav en god dag.", "ja", "nej"),
    "ta": ("Tamil", "வணக்கம்", "இனிய நாள்.", "ஆம்", "இல்லை"),
    "uk": ("Ukrainian", "Вітаю", "Гарного дня.", "так", "ні"),
    "ru": ("Russian", "Здравствуйте", "Хорошего дня.", "да", "нет"),
    "hu": ("Hungarian", "Szia", "Szép napot.", "igen", "nem"),
    "no": ("Norwegian", "Hei", "Ha en fin dag.", "ja", "nei"),
    "vi": ("Vietnamese", "Xin chào", "Chúc bạn một ngày tốt lành.", "vâng", "không"),
}

# Generate full translations for remaining languages
for _code, (_name, _hello, _goodbye, _yes, _no) in _REMAINING.items():
    MESSAGES[_code] = {
        "irrelevant_shutdown": f"{MESSAGES['en']['irrelevant_shutdown'].replace('Have a nice day.', _goodbye)}",
        "recruiter_handoff": MESSAGES["en"]["recruiter_handoff"],
        "silence_prompt": MESSAGES["en"]["silence_prompt"],
        "silence_shutdown": f"{MESSAGES['en']['silence_shutdown'].replace('Have a nice day.', _goodbye)}",
        "screening_unclear": f"{MESSAGES['en']['screening_unclear'].replace('Have a nice day.', _goodbye)}",
        "ready_check": MESSAGES["en"]["ready_check"],
        "ready_check_decline": f"{MESSAGES['en']['ready_check_decline'].replace('Have a nice day.', _goodbye)}",
        "open_questions_thanks": MESSAGES["en"]["open_questions_thanks"],
        "existing_booking": f"{MESSAGES['en']['existing_booking'].replace('Have a nice day.', _goodbye)}",
        "scheduling_invite": MESSAGES["en"]["scheduling_invite"],
        "scheduling_confirm": f"{MESSAGES['en']['scheduling_confirm'].replace('Have a nice day.', _goodbye)}",
        "scheduling_followup_tomorrow": MESSAGES["en"]["scheduling_followup_tomorrow"],
        "scheduling_followup_later": MESSAGES["en"]["scheduling_followup_later"],
        "scheduling_preference": f"{MESSAGES['en']['scheduling_preference'].replace('Have a nice day.', _goodbye)}",
        "recruiter_greeting": MESSAGES["en"]["recruiter_greeting"],
        "recruiter_goodbye": f"{MESSAGES['en']['recruiter_goodbye'].replace('Have a nice day.', _goodbye)}",
        "alternative_thanks": f"{MESSAGES['en']['alternative_thanks'].replace('Have a nice day.', _goodbye)}",
        "alternative_not_interested": f"{MESSAGES['en']['alternative_not_interested'].replace('Have a nice day.', _goodbye)}",
        "voicemail_with_name": f"{_hello} {{name}}, this is {{persona_name}} from Go For Jobs. We called you regarding your application. Feel free to call us back when it suits you. {_goodbye}",
        "voicemail_without_name": f"{_hello}, this is {{persona_name}} from Go For Jobs. We called you regarding your application. Feel free to call us back when it suits you. {_goodbye}",
        "proxy_detected": f"{MESSAGES['en']['proxy_detected'].replace('Have a nice day.', _goodbye)}",
        "candidate_not_available": f"{MESSAGES['en']['candidate_not_available'].replace('Have a nice day.', _goodbye)}",
        "agent_greeting": MESSAGES["en"]["agent_greeting"],
    }

# All supported language codes
SUPPORTED_LANGUAGES = list(MESSAGES.keys())
