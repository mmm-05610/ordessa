import React from 'react'
import { createRoot } from 'react-dom/client'
import { Board } from '@ordessa/status-board'
import '@ordessa/status-board/styles.css'
import { composeBoard } from './composition'
createRoot(document.getElementById('root')!).render(<Board {...composeBoard()} />)
