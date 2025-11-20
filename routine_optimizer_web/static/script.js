// script.js - dark mode and small helpers with accessible focus
window.initDarkMode = function(){
  const btn = document.getElementById('dark-toggle');
  const mode = localStorage.getItem('dark') === '1';
  if(mode) document.body.classList.add('dark');
  btn && btn.addEventListener('click', ()=>{
    const is = document.body.classList.toggle('dark');
    localStorage.setItem('dark', is ? '1' : '0');
    // small animation: pulse the page
    document.body.animate([{filter:'brightness(1.03)'},{filter:'brightness(1)'}],{duration:240});
  });
};

// small helper to enlarge hit target (if JS needed); CSS already handles hit area via padding.
// Focus outlines for keyboard users
document.addEventListener('keydown', function(e){
  if(e.key === 'Tab') document.body.classList.add('show-focus');
});
document.addEventListener('mousedown', function(){ document.body.classList.remove('show-focus'); });