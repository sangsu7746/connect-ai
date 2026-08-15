import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import PostList from './pages/PostList'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/category/:id" element={<PostList />} />
      </Routes>
    </BrowserRouter>
  )
}
