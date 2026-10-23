import React from 'react';
import ReactDOM from 'react-dom/client';
import { AppearanceProvider } from './AppearanceProvider';
import App from './App';
import './global.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AppearanceProvider>
      <App />
    </AppearanceProvider>
  </React.StrictMode>,
);
