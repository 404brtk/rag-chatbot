import { createBrowserRouter } from 'react-router';
import App from './App';
import { ChatPage } from './pages/ChatPage';
import { HistoryPage } from './pages/HistoryPage';
import { APP_ROUTES } from './routes';

export const router = createBrowserRouter([
  {
    path: '/',
    Component: App,
    children: [
      {
        index: true,
        Component: ChatPage,
      },
      {
        path: APP_ROUTES.chatDetail.slice(1),
        Component: ChatPage,
      },
      {
        path: APP_ROUTES.history.slice(1),
        Component: HistoryPage,
      },
    ],
  },
]);
