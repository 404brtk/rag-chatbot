import { useState, useEffect, useRef } from 'react';
import { api } from '../services/api';
import { useLocalStorage } from './useLocalStorage';
import { useAuth } from './useAuth';

export function useModelConfig() {
  const { isAuthenticated } = useAuth();
  const [models, setModels] = useState<Record<string, string[]>>({});
  const [provider, setProvider] = useLocalStorage<string>('chat_provider', 'openai');
  const [model, setModel] = useLocalStorage<string>('chat_model', '');

  const providerRef = useRef(provider);
  const modelRef = useRef(model);

  useEffect(() => {
    providerRef.current = provider;
  }, [provider]);

  useEffect(() => {
    modelRef.current = model;
  }, [model]);

  useEffect(() => {
    let ignore = false;

    const loadModels = async () => {
      if (!isAuthenticated) {
        setModels({});
        return;
      }
      try {
        const data = await api.get<Record<string, string[]>>('/models/');
        if (ignore) return;
        setModels(data);
        const providers = Object.keys(data);
        if (providers.length > 0) {
          const currentProvider = providerRef.current;
          const currentModel = modelRef.current;

          const nextProvider =
            currentProvider && providers.includes(currentProvider)
              ? currentProvider
              : providers.includes('openai')
                ? 'openai'
                : providers[0];

          const allowedModels = data[nextProvider] || [];
          const nextModel =
            currentProvider === nextProvider && currentModel && allowedModels.includes(currentModel)
              ? currentModel
              : allowedModels[0] || '';

          setProvider(nextProvider);
          setModel(nextModel);
        }
      } catch (err) {
        console.error('Failed to load models:', err);
      }
    };

    loadModels();

    return () => {
      ignore = true;
    };
  }, [isAuthenticated, setModel, setProvider]);

  return {
    provider,
    model,
    setProvider,
    setModel,
    models,
  };
}
