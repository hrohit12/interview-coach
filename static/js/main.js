/**
 * main.js - Shared utilities for Interview Coach
 */

// Ensure user is authenticated (has setup data in sessionStorage)
function requireSetup(redirect = '/') {
  const key = sessionStorage.getItem('ic_api_key');
  const name = sessionStorage.getItem('ic_name');
  if (!key || !name) {
    window.location.href = redirect;
    return false;
  }
  return true;
}

// Format seconds as MM:SS
function formatTime(seconds) {
  const m = Math.floor(seconds / 60).toString().padStart(2, '0');
  const s = (seconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

// Simple toast notification
function showToast(message, type = 'info') {
  const existing = document.getElementById('ic-toast');
  if (existing) existing.remove();

  const colors = {
    info: 'bg-slate-800 text-white',
    success: 'bg-green-700 text-white',
    error: 'bg-red-700 text-white',
    warning: 'bg-orange-600 text-white',
  };

  const toast = document.createElement('div');
  toast.id = 'ic-toast';
  toast.className = `fixed bottom-4 right-4 z-[999] px-4 py-2.5 rounded-xl text-sm font-medium shadow-xl ${colors[type] || colors.info} transition-all duration-300 max-w-xs`;
  toast.textContent = message;

  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}
