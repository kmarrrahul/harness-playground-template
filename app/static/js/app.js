/**
 * app.js — Alpine.js entry-point for Harness Playground.
 *
 * Composes authMixin + featuresMixin into a single x-data store.
 * All lib/ and mixin/ scripts must be loaded before this file.
 */

/* eslint-disable no-undef */

window.appStore = function () {
  return {
    // Spread mixins
    ...authMixin(),
    ...featuresMixin(),
    ...skillsMixin(),
    currentTheme: localStorage.getItem('harness_theme') || 'solarized-dark',
    
    themes: [
      { id: 'dark', name: 'Dark Mode' },
      { id: 'solarized-dark', name: 'Solarized Dark' },
      { id: 'light', name: 'Solarized Light' },
      { id: 'mint', name: 'Cool Mint Green' },
      { id: 'olive', name: 'Warm Olive' },
      { id: 'matcha', name: 'True Matcha' }
    ],

    setTheme(themeId) {
      this.currentTheme = themeId;
      localStorage.setItem('harness_theme', themeId);
      
      document.documentElement.classList.remove('light-theme', 'theme-solarized-dark', 'theme-mint', 'theme-olive', 'theme-matcha');
      
      if (themeId === 'light') document.documentElement.classList.add('light-theme');
      else if (themeId === 'solarized-dark') document.documentElement.classList.add('theme-solarized-dark');
      else if (themeId === 'mint') document.documentElement.classList.add('theme-mint');
      else if (themeId === 'olive') document.documentElement.classList.add('theme-olive');
      else if (themeId === 'matcha') document.documentElement.classList.add('theme-matcha');
    },

    init() {
      console.log('[Harness Playground] Initialising…');
      // Migration from old light-theme toggle
      if (localStorage.getItem('playground_light_theme') === 'false') {
        this.setTheme('dark');
        localStorage.removeItem('playground_light_theme');
      } else {
        this.setTheme(this.currentTheme);
      }
      initMermaid();
      configureMarked();
      this.initAuth();
    },
  };
};
