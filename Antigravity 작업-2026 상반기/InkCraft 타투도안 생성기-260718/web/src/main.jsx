import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import './styles.css';

// 크롬 자동번역(구글 번역)이 DOM을 변형해 React의 insertBefore/removeChild가
// 크래시하는 문제 방어. 번역기가 만든 노드 불일치를 조용히 우회한다.
if (typeof Node === 'function' && Node.prototype) {
  const originalRemoveChild = Node.prototype.removeChild;
  Node.prototype.removeChild = function (child) {
    if (child.parentNode !== this) {
      console.warn('[translate-guard] skipped removeChild for foreign node');
      return child;
    }
    return originalRemoveChild.apply(this, arguments);
  };
  const originalInsertBefore = Node.prototype.insertBefore;
  Node.prototype.insertBefore = function (newNode, referenceNode) {
    if (referenceNode && referenceNode.parentNode !== this) {
      console.warn('[translate-guard] insertBefore fallback to appendChild');
      return this.appendChild(newNode);
    }
    return originalInsertBefore.apply(this, arguments);
  };
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
