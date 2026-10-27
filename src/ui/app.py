import os

import streamlit as st


COPY = {
    "en": {
        "name": "English",
        "title": "Scheme Saathi",
        "subtitle": "A multilingual welfare-scheme navigator",
        "banner": "SYNTHETIC DEMONSTRATION — NOT A GOVERNMENT SERVICE",
        "message": "The guided demonstration journey will appear here next.",
    },
    "hi": {
        "name": "हिन्दी",
        "title": "स्कीम साथी",
        "subtitle": "बहुभाषी कल्याण-योजना मार्गदर्शक",
        "banner": "कृत्रिम प्रदर्शन — यह सरकारी सेवा नहीं है",
        "message": "निर्देशित प्रदर्शन यात्रा का अगला संस्करण यहाँ दिखाई देगा।",
    },
    "mr": {
        "name": "मराठी",
        "title": "स्कीम साथी",
        "subtitle": "बहुभाषिक कल्याण-योजना मार्गदर्शक",
        "banner": "कृत्रिम प्रात्यक्षिक — ही सरकारी सेवा नाही",
        "message": "मार्गदर्शित प्रात्यक्षिक प्रवासाची पुढील आवृत्ती येथे दिसेल.",
    },
}


st.set_page_config(
    page_title="Scheme Saathi",
    page_icon="🤝",
    layout="centered",
)

st.markdown(
    """
    <style>
    .demo-banner {
        background: #7f1d1d;
        border-radius: 0.5rem;
        color: #ffffff;
        font-weight: 700;
        margin-bottom: 1.5rem;
        padding: 0.9rem;
        text-align: center;
    }
    .version {
        color: #4b5563;
        font-size: 0.85rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

locale = st.selectbox(
    "Language / भाषा / भाषा",
    options=list(COPY),
    format_func=lambda value: COPY[value]["name"],
)
text = COPY[locale]

st.markdown(
    f'<div class="demo-banner">{text["banner"]}</div>',
    unsafe_allow_html=True,
)
st.title(text["title"])
st.subheader(text["subtitle"])
st.info(text["message"])
st.markdown(
    f'<p class="version">Prototype version: '
    f'{os.getenv("APP_VERSION", "development")}</p>',
    unsafe_allow_html=True,
)
