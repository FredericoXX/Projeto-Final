import { useTranslation } from '../../i18n/useTranslation';

interface FormActionsProps {
  pending: boolean;
  // Guardar é sempre submit (Enter no formulário executa-o).
  saveLabel?: string;
  // Guardar e Novo é opcional e nunca é o submit do formulário.
  onSaveAndNew?: () => void;
  onCancel: () => void;
}

// Ações padrão de formulários de criação/edição: Guardar (submit),
// Guardar e Novo (opcional) e Cancelar, todas desativadas enquanto a
// mutation está pendente para impedir pedidos duplicados.
export function FormActions({ pending, saveLabel, onSaveAndNew, onCancel }: FormActionsProps) {
  const { t } = useTranslation();
  return (
    <div className="composer-row form-actions">
      <button type="submit" className="btn btn-primary" disabled={pending}>
        {pending ? t('form.saving') : (saveLabel ?? t('form.save'))}
      </button>
      {onSaveAndNew && (
        <button
          type="button"
          className="btn btn-secondary"
          disabled={pending}
          onClick={onSaveAndNew}
        >
          {t('form.saveAndNew')}
        </button>
      )}
      <button type="button" className="btn btn-ghost" disabled={pending} onClick={onCancel}>
        {t('common.cancel')}
      </button>
    </div>
  );
}
