
document.addEventListener("DOMContentLoaded", function () {

    // Automatically hide flash messages after 5 seconds
    const alerts = document.querySelectorAll(".alert");

    alerts.forEach(function (alert) {
        setTimeout(function () {
            if (typeof bootstrap !== "undefined") {
                const alertInstance = bootstrap.Alert.getOrCreateInstance(alert);
                alertInstance.close();
            }
        }, 5000);
    });

    // Confirm before logging out
    const logoutLinks = document.querySelectorAll(
        'a[href*="/logout"]'
    );

    logoutLinks.forEach(function (link) {
        link.addEventListener("click", function (event) {
            if (!confirm("Are you sure you want to log out?")) {
                event.preventDefault();
            }
        });
    });

});
