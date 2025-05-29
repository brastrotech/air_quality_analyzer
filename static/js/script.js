$(document).ready(function() {
    $('#uploadForm').on('submit', function(e) {
        // ... (event handling setup as before) ...
        e.preventDefault();

        $('#loading').show();
        $('#results').empty();
        $('#errorMessages').hide().empty();
        $('#warningMessages').hide().empty();
        $('#infoMessages').hide().empty();
        $('#downloadLinks').hide();
        $('#downloadCsvLinkContainer').hide();
        $('#downloadPlotsZipLinkContainer').hide();

        var formData = new FormData(this);

        $.ajax({
            url: '/process',
            type: 'POST',
            data: formData,
            contentType: false,
            processData: false,
            success: function(response) {
                // ... (error, warning, info, download link handling as before) ...
                $('#loading').hide();
                if (response.error) {
                    let errorText = 'Error: ' + response.error;
                    if (response.details) {
                        errorText += ' Details: ' + (Array.isArray(response.details) ? response.details.join('<br>') : response.details);
                    }
                    $('#errorMessages').html(errorText).show();
                    return; 
                }

                if (response.warnings && response.warnings.length > 0) {
                    let warningsHtml = '<strong>Warnings/Issues:</strong><ul>';
                    response.warnings.forEach(warn => {
                        warningsHtml += `<li>${warn}</li>`;
                    });
                    warningsHtml += '</ul>';
                    $('#warningMessages').html(warningsHtml).show();
                }
                
                if (response.message) {
                    $('#infoMessages').text(response.message).show();
                }

                let downloadsAvailable = false;
                if (response.processed_csv_url) {
                    $('#downloadCsvLink').attr('href', response.processed_csv_url);
                    $('#downloadCsvLinkContainer').show();
                    downloadsAvailable = true;
                }
                if (response.plots_zip_url) {
                    $('#downloadPlotsZipLink').attr('href', response.plots_zip_url);
                    $('#downloadPlotsZipLinkContainer').show();
                    downloadsAvailable = true;
                }
                if(downloadsAvailable) {
                    $('#downloadLinks').show();
                }

                if (response.plots) {
                    displayPlots(response.plots);
                } else if (!response.error && (!response.warnings || response.warnings.length === 0) && !response.message) {
                    $('#infoMessages').text("Processing completed, but no plots or specific messages were returned.").show();
                }
            },
            error: function(jqXHR, textStatus, errorThrown) {
                // ... (error handling as before) ...
                 $('#loading').hide();
                let errorMsg = 'An unexpected error occurred during processing.';
                if (jqXHR.responseJSON) {
                    errorMsg = 'Error: ' + (jqXHR.responseJSON.error || 'Unknown server error.');
                    if (jqXHR.responseJSON.details) {
                        errorMsg += ' Details: ' + (Array.isArray(jqXHR.responseJSON.details) ? jqXHR.responseJSON.details.join('<br>') : jqXHR.responseJSON.details);
                    }
                } else if (jqXHR.responseText) {
                    try {
                        if (jqXHR.responseText.trim().startsWith('<')) {
                             errorMsg = `Server Error: ${jqXHR.status} - ${errorThrown}. The server returned an HTML error page. Check the browser console and Flask server logs for details.`;
                        } else {
                            const errResp = JSON.parse(jqXHR.responseText);
                            errorMsg = 'Error: ' + (errResp.error || errorThrown);
                        }
                    } catch (e) {
                        errorMsg = `Server Error: ${jqXHR.status} - ${errorThrown}. Response: ${jqXHR.responseText.substring(0, 300)}...`;
                    }
                }
                $('#errorMessages').html(errorMsg).show();
                console.error("AJAX Error:", textStatus, errorThrown, jqXHR);
                console.error("Response Text:", jqXHR.responseText);
            }
        });
    });

    function displayPlots(plots) {
        const resultsDiv = $('#results');
        resultsDiv.empty(); 

        if (plots.pm25_timeseries) {
            resultsDiv.append('<h2>PM2.5 Time Series</h2>');
            resultsDiv.append(`<img src="data:image/png;base64,${plots.pm25_timeseries}" class="img-fluid mb-3" alt="PM2.5 Time Series">`);
        }
        if (plots.pm10_timeseries) {
            resultsDiv.append('<h2>PM10 Time Series</h2>');
            resultsDiv.append(`<img src="data:image/png;base64,${plots.pm10_timeseries}" class="img-fluid mb-3" alt="PM10 Time Series">`);
        }

        // Overall Diurnal Variations (with SD/SE)
        if (plots.diurnal_variations_overall && Object.keys(plots.diurnal_variations_overall).length > 0) {
            resultsDiv.append('<h2>Average Diurnal Variations (Overall)</h2>');
            for (const paramKey in plots.diurnal_variations_overall) {
                let displayParamName = paramKey.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                resultsDiv.append(`<h3>${displayParamName}</h3>`);
                resultsDiv.append(`<img src="data:image/png;base64,${plots.diurnal_variations_overall[paramKey]}" class="img-fluid mb-3" alt="Overall Diurnal Variation for ${displayParamName}">`);
            }
        }

        // Diurnal Variations by Day of the Week (Mean lines)
        if (plots.diurnal_variations_by_day_of_week && Object.keys(plots.diurnal_variations_by_day_of_week).length > 0) {
            resultsDiv.append('<h2>Average Diurnal Variations by Day of Week</h2>');
            for (const paramKey in plots.diurnal_variations_by_day_of_week) {
                let displayParamName = paramKey.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                resultsDiv.append(`<h3>${displayParamName}</h3>`);
                resultsDiv.append(`<img src="data:image/png;base64,${plots.diurnal_variations_by_day_of_week[paramKey]}" class="img-fluid mb-3" alt="Diurnal Variation by Day of Week for ${displayParamName}">`);
            }
        }


        if (resultsDiv.is(':empty') && !$('#infoMessages').is(':visible') && !$('#warningMessages').is(':visible') && !$('#errorMessages').is(':visible')) {
             resultsDiv.append('<p class="text-muted">No plots were generated. Check console or warnings for details.</p>');
        }
    }
});