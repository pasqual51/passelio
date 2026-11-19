'use strict';
Object.assign(translations.fr,{home_navigation:'Espace personnel',home_new:'Nouveau partage',home_shares:'Mes partages',home_email:'Envoyer un lien par email',home_requests:'Demander des fichiers',home_history:'Historique des emails',home_profile:'Mon profil et sécurité',home_email_help:'Choisissez un partage actif, puis indiquez les destinataires. Le lien sera envoyé par le serveur SMTP configuré par votre administrateur.',home_choose_share:'Choisir un partage',home_no_shares:'Créez un partage pour pouvoir envoyer son lien par email.'});
Object.assign(translations.en,{home_navigation:'My workspace',home_new:'New share',home_shares:'My shares',home_email:'Email a share link',home_requests:'Request files',home_history:'Email history',home_profile:'My profile and security',home_email_help:'Choose an active share and enter the recipients. The link will be sent through the SMTP server configured by your administrator.',home_choose_share:'Choose a share',home_no_shares:'Create a share before sending its link by email.'});
const homeLayout=element('div',undefined,'home-layout'),homeNav=element('nav',undefined,'home-nav'),homeBody=element('div',undefined,'home-body');
homeNav.setAttribute('aria-label',t('home_navigation'));homeLayout.append(homeNav,homeBody);
const homePanels={},homeButtons={};let homeSection='new';
for(const [key,label] of [['new','home_new'],['shares','home_shares'],['email','home_email'],['requests','home_requests'],['history','home_history'],['profile','home_profile']]){
 const panel=element('section');panel.id='home-'+key;panel.className='home-panel';panel.hidden=key!==homeSection;homePanels[key]=panel;homeBody.append(panel);
 const button=element('button',t(label));button.type='button';button.dataset.i18n=label;button.setAttribute('aria-controls',panel.id);button.addEventListener('click',()=>selectHome(key));homeButtons[key]=button;homeNav.append(button);
}
homePanels.new.append(document.querySelector('#dashboard > .workspace'));
homePanels.shares.append($('shares').closest('section'));
homePanels.history.append($('my-mail-jobs').closest('section'));
homePanels.requests.append($('request-create-form').closest('section'));
for(const node of [...$('dashboard').children])if(node!==homeLayout)homePanels.profile.append(node);
$('dashboard').append(homeLayout);
const mailCard=element('section',undefined,'card');const mailHeading=element('h2',t('home_email'));mailHeading.dataset.i18n='home_email';const mailHelp=element('p',t('home_email_help'),'muted');mailHelp.dataset.i18n='home_email_help';const shareLabel=element('label',t('home_choose_share'));shareLabel.htmlFor='home-email-share';shareLabel.dataset.i18n='home_choose_share';const shareChoice=element('select');shareChoice.id='home-email-share';const noShares=element('p',t('home_no_shares'),'muted');noShares.dataset.i18n='home_no_shares';mailCard.append(mailHeading,mailHelp,shareLabel,shareChoice,noShares,$('result'));homePanels.email.append(mailCard);
function selectHome(key){if(!homePanels[key])return;homeSection=key;for(const name of Object.keys(homePanels)){homePanels[name].hidden=name!==key;homeButtons[name].classList.toggle('selected',name===key);if(name===key)homeButtons[name].setAttribute('aria-current','page');else homeButtons[name].removeAttribute('aria-current');}if(key==='email')refreshHomeEmail();}
function setEmailShare(id){const share=currentData?.shares.find(s=>s.id===id&&!s.revoked&&s.expires*1000>Date.now());if(!share)return;lastShareId=share.id;shareChoice.value=share.id;$('share-link').value=(instanceConfig?.application_url||location.origin)+'/s/'+share.id;$('notify-language').value=lang;$('result').hidden=false;}
function refreshHomeEmail(){const previous=lastShareId||shareChoice.value;shareChoice.replaceChildren();const active=(currentData?.shares||[]).filter(s=>!s.revoked&&s.expires*1000>Date.now());for(const share of active){const option=element('option',share.title);option.value=share.id;shareChoice.append(option);}shareChoice.disabled=!active.length;noShares.hidden=!!active.length;if(active.length&&homeSection==='email')setEmailShare(active.some(s=>s.id===previous)?previous:active[0].id);else if(!active.length)$('result').hidden=true;}
shareChoice.addEventListener('change',()=>setEmailShare(shareChoice.value));
window.openShareEmail=share=>{lastShareId=share.id;selectHome('email');setEmailShare(share.id);$('notify-to').focus();};
const beforeHomeShares=renderShares;renderShares=()=>{beforeHomeShares();refreshHomeEmail();};
const beforeHomeStart=start;start=async()=>{await beforeHomeStart();selectHome(homeSection);};
const beforeHomeTranslate=translate;translate=()=>{beforeHomeTranslate();homeNav.setAttribute('aria-label',t('home_navigation'));};
selectHome('new');
