/**
 * Modal helper component.
 * Requires: css/components/modals.css
 *
 * Usage:
 *   Modal.open('myModalId');
 *   Modal.close('myModalId');
 *   Modal.init();  // auto-bind close on overlay click & cancel buttons
 */
const Modal = {
    open(id) {
        const el = document.getElementById(id);
        if (el) el.classList.add('open');
    },

    close(id) {
        const el = document.getElementById(id);
        if (el) el.classList.remove('open');
    },

    /** Auto-bind close behaviour: click overlay backdrop → close, [data-modal-close] → close */
    init() {
        document.addEventListener('click', function (e) {
            if (e.target.classList.contains('modal-overlay') && e.target.classList.contains('open')) {
                e.target.classList.remove('open');
            }
            const closer = e.target.closest('[data-modal-close]');
            if (closer) {
                const overlay = closer.closest('.modal-overlay');
                if (overlay) overlay.classList.remove('open');
            }
        });
    },
};
