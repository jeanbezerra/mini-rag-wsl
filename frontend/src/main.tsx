import React from 'react';
import ReactDOM from 'react-dom/client';
import { createLightTheme, FluentProvider, type BrandVariants } from '@fluentui/react-components';
import App from './App';
import './global.css';

const brand: BrandVariants = {
  10: '#021311', 20: '#032824', 30: '#074138', 40: '#095247',
  50: '#0c6256', 60: '#0e7366', 70: '#118477', 80: '#159589',
  90: '#25a69a', 100: '#44b6aa', 110: '#63c5ba', 120: '#83d3ca',
  130: '#a3e0d9', 140: '#c2ece7', 150: '#dff6f2', 160: '#f2fcfa',
};
const theme = createLightTheme(brand);
// The primary foreground/background pair uses a darker brand step for readable white text.
theme.colorBrandBackground = brand[60];
theme.colorBrandBackgroundHover = brand[50];
theme.colorBrandBackgroundPressed = brand[40];
theme.colorBrandForeground1 = brand[50];
theme.colorBrandForeground2 = brand[40];
theme.colorBrandStroke1 = brand[60];

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <FluentProvider theme={theme}>
      <App />
    </FluentProvider>
  </React.StrictMode>,
);
