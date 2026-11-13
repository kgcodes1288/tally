import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { Demo } from './components/Demo.tsx'

// /demo is the public, read-only replay gallery (no login); everything else is the signed-in app.
const isDemo = window.location.pathname === '/demo' || window.location.pathname.startsWith('/demo/')
createRoot(document.getElementById('root')!).render(<StrictMode>{isDemo ? <Demo /> : <App />}</StrictMode>)
