(function() {
    // Wait for DOM to load
    document.addEventListener('DOMContentLoaded', function() {
        // Initial stat update
        updateStats();

        // Poll every 5 seconds
        setInterval(updateStats, 5000);
    });

    function updateStats() {
        fetch('/api/status/')
            .then(response => response.json())
            .then(data => {
                // Update stat cards
                let total = data.applications.length;
                let pending = 0, processing = 0, finalizing = 0, success = 0, failed = 0;
                data.applications.forEach(app => {
                    switch(app.status) {
                        case 'PENDING': pending++; break;
                        case 'PROCESSING': processing++; break;
                        case 'FINALIZING': finalizing++; break;
                        case 'SUCCESS': success++; break;
                        case 'FAILED':
                        case 'CANCELED':
                            failed++; break;
                    }
                });

                document.getElementById('stat-total').textContent = total;
                document.getElementById('stat-pending').textContent = pending;
                document.getElementById('stat-processing').textContent = processing;
                // We don't have a separate FINALIZING stat card, but we can combine or add
                // For simplicity, we can treat processing+finalizing as running
                document.getElementById('stat-success').textContent = success;
                document.getElementById('stat-failed').textContent = failed;

                // Also update status badges and action buttons if needed
                // But we'll rely on page reloads or incremental updates.
                // For a more dynamic experience, you can compare and update specific rows.
            })
            .catch(err => console.error('Stats update error:', err));
    }
})();