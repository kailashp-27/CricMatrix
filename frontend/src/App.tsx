import { ArrowDownLeft } from 'lucide-react'
import { useEffect, useState } from 'react'
import { LiveMatches } from './components/LiveMatches'
import { ProviderTables } from './components/ProviderTables'

export default function App() {
  const [view, setView] = useState(() => window.location.hash === '#across-competitions' ? 'scores' : 'tables')
  useEffect(() => {
    const update = () => setView(window.location.hash === '#across-competitions' ? 'scores' : 'tables')
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [])
  return <div className="app-shell">
    <header className="topbar"><a className="brand" href="/" aria-label="CricMatrix home"><span className="brand-mark"><i /><i /><i /></span>CricMatrix<span className="brand-dot">.</span></a><nav aria-label="Main"><a className={view === 'tables' ? 'nav-active' : ''} href="#table" aria-current={view === 'tables' ? 'page' : undefined}>Tables & predictions</a><a className={view === 'scores' ? 'nav-active' : ''} href="#across-competitions" aria-current={view === 'scores' ? 'page' : undefined}>Cricket across competitions</a></nav></header>
    <main>
      <div className="eyebrow"><span /> CRICKET ACROSS COMPETITIONS</div>
      <section className="intro"><div><h1>Every match changes<br />the <em>picture.</em></h1><p>Fetched scores, results and tournament tables.<br />See the source. Know when it was updated.</p></div><div className="intro-note"><span className="tiny-label">AROUND THE GROUNDS</span><p>Follow the matches.<br />Explore the tables.</p><ArrowDownLeft className="note-arrow" size={62} strokeWidth={1} /></div></section>
      <div hidden={view !== 'scores'}><LiveMatches /></div>
      <div hidden={view !== 'tables'}><ProviderTables /></div>
      <footer><a className="brand" href="/">CricMatrix<span className="brand-dot">.</span></a><span>Cricket is a game of possibilities.</span><span className="footer-build">PROVIDER SNAPSHOTS</span></footer>
    </main>
  </div>
}
