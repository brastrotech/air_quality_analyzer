$(document).ready(function() {
    $('#uploadForm').on('submit', function(e) {
        e.preventDefault();

        $('#loading').show();
        $('#results').empty();
        $('#errorMessages').hide().empty();
        $('#warningMessages').hide().empty();

        var formData = new FormData(this);

        $.ajax({
            url: '/process',
            type: 'POST',
            data: formData,
            contentType: false,
            processData: false,
            success: function(response) {
                $('#loading').hide();
                if (response.error) {
                    $('#errorMessages').text('Error: ' + response.error + (response.details ? ' Details: ' + response.details.join(', ') : '')).show();
                    return;
                }
                if (response.warnings && response.warnings.length > 0) {
                    let warningsHtml = '<strong>Warnings:</strong><ul>';
                    response.warnings.forEach(warn => {
                        warningsHtml += `<li>${warn}</li>`;
                    });
                    warningsHtml += '</ul>';
                    $('#warningMessages').html(warningsHtml).show();
                }

                displayPlots(response.plots);
            },
            error: function(jqXHR, textStatus, errorThrown) {
                $('#loading').hide();
                let errorMsg = 'An unexpected error occurred.';
                if (jqXHR.responseJSON && jqXHR.responseJSON.error) {
                    errorMsg = 'Error: ' + jqXHR.responseJSON.error;
                     if (jqXHR.responseJSON.details) {
                        errorMsg += ' Details: ' + jqXHR.responseJSON.details.join(', ');
                    }
                } else if (jqXHR.responseText) {
                    try {
                        const errResp = JSON.parse(jqXHR.responseText);
                        errorMsg = 'Error: ' + (errResp.error || errorThrown);
                    } catch (e) {
                        errorMsg = `Server Error: ${jqXHR.status} - ${errorThrown}`;
                    }
                }
                $('#errorMessages').text(errorMsg).show();
                console.error("AJAX Error:", textStatus, errorThrown, jqXHR.responseText);
            }
        });
    });

    function displayPlots(plots) {
        const resultsDiv = $('#results');
        resultsDiv.empty(); // Clear previous results

        if (plots.pm2_5_timeseries) {
            resultsDiv.append('<h2>PM2.5 Time Series</h2>');
            resultsDiv.append(`<img src="data:image/png;base64,${plots.pm2_5_timeseries}" class="img-fluid mb-3" alt="PM2.5 Time Series">`);
        }
        if (plots.pm10_timeseries) {
            resultsDiv.append('<h2>PM10 Time Series</h2>');
            resultsDiv.append(`<img src="data:image/png;base64,${plots.pm10_timeseries}" class="img-fluid mb-3" alt="PM10 Time Series">`);
        }

        if (plots.diurnal_variations && Object.keys(plots.diurnal_variations).length > 0) {
            resultsDiv.append('<h2>Diurnal Variations</h2>');
            for (const param in plots.diurnal_variations) {
                resultsDiv.append(`<h3>${param}</h3>`);
                resultsDiv.append(`<img src="data:image/png;base64,${plots.diurnal_variations[param]}" class="img-fluid mb-3" alt="Diurnal Variation for ${param}">`);
            }
        }

        if (resultsDiv.is(':empty')) {
             resultsDiv.append('<p class="text-muted">No plots were generated. This might be due to missing PM2.5/PM10 data or no other numeric columns for diurnal analysis.</p>');
        }
    }
});