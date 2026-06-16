# Set your password
$password = "changeit"

# 1. Get ONLY the lines containing 'trustedCertEntry'
# Redirect 2>$null ignores the "Picked up JAVA_TOOL_OPTIONS" warning
$certLines = keytool -list -cacerts -storepass $password 2>$null | Select-String "trustedCertEntry"

if ($certLines.Count -eq 0) {
    Write-Error "No trusted certificates found. Check your password or Java installation."
    return
}

foreach ($line in $certLines) {
    # 2. Extract the alias (it's the first part of the comma-separated line)
    $alias = $line.ToString().Split(',')[0].Trim()
    
    if ($alias) {
        Write-Host "Exporting: $alias"
        # 3. Export using the alias, putting it in quotes to handle spaces
        # We use --% to pass the command directly to the native tool
        & keytool -exportcert -cacerts -alias "$alias" -storepass $password -file "$($alias -replace '[^\w\d]', '_').crt" -rfc 2>$null
    }
}