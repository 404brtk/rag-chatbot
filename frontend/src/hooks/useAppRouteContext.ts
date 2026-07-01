import { useOutletContext } from 'react-router';
import type { AppRouteContext } from '../types';

export function useAppRouteContext() {
  return useOutletContext<AppRouteContext>();
}
