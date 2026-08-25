# ByteSqueeze iPhone and iPad TestFlight setup

ByteSqueeze is one universal Flutter app for iPhone and iPad. Both platforms use the same controller, worker, queue, Smart Preset, Size Wizard, library, and settings features. The iPad layout automatically changes to the wider sidebar workspace and supports portrait, landscape, Split View, keyboard, and pointer input.

The repository validates an unsigned Apple-device build on every relevant push. Publishing is separate and manual in the **Publish ByteSqueeze to TestFlight** GitHub Actions workflow.

## 1. Create the Apple app identity

1. Enroll the Apple Account that will own ByteSqueeze in the Apple Developer Program.
2. In **Certificates, Identifiers & Profiles**, register an explicit App ID. The project default is `com.kevina1724.bytesqueeze`.
3. In App Store Connect, create a new iOS app named **ByteSqueeze** using that exact bundle ID. A practical SKU is `bytesqueeze-ios`.
4. If you choose a different bundle ID, add a GitHub Actions repository or `testflight` environment variable named `IOS_BUNDLE_ID`. The publishing workflow updates the Xcode project for that build.

Choose the bundle ID carefully. Apple associates uploads with it and it cannot be changed after the first build is uploaded.

## 2. Create upload credentials

In App Store Connect, open **Users and Access → Integrations → App Store Connect API**. Create a **team API key** with the **App Manager** role and download its `AuthKey_*.p8` file immediately. Apple only lets you download the private key once.

Create an **Apple Distribution** certificate whose private key is in your Mac keychain, then export the certificate and private key together from Keychain Access as a password-protected `.p12`.

The workflow downloads the matching App Store provisioning profile through Apple's API. If no profile exists yet, create an **App Store Connect** distribution profile for the explicit ByteSqueeze App ID and Apple Distribution certificate.

## 3. Configure GitHub safely

Open the GitHub repository, then **Settings → Environments → New environment**, and create an environment named `testflight`. Add these values to that environment (repository-level Actions values also work):

Variables:

- `APPSTORE_ISSUER_ID`: the Issuer ID from the App Store Connect API page.
- `APPSTORE_API_KEY_ID`: the Key ID for `AuthKey_*.p8`.
- `IOS_BUNDLE_ID`: optional; omit it to use `com.kevina1724.bytesqueeze`.

Secrets:

- `APPSTORE_API_PRIVATE_KEY`: the complete text of `AuthKey_*.p8`, including its BEGIN/END lines.
- `APPSTORE_CERTIFICATES_FILE_BASE64`: the exported distribution `.p12` encoded as base64.
- `APPSTORE_CERTIFICATES_PASSWORD`: the password used when exporting the `.p12`.

On a Mac, copy the certificate value without creating another unprotected file:

```bash
base64 -i ByteSqueeze-Distribution.p12 | pbcopy
```

Never commit or send the `.p8`, `.p12`, or their passwords in chat. GitHub masks secrets and gives the temporary macOS build runner access only while the manual workflow runs.

## 4. Upload the first build

1. Open the repository's **Actions** tab.
2. Select **Publish ByteSqueeze to TestFlight**.
3. Choose **Run workflow** on `main`.
4. Leave the build number blank unless App Store Connect says that number was already used.
5. Enter concise tester notes and run it.

The workflow tests the app, builds and signs the universal IPA, uploads it, and waits for App Store Connect processing. A normal push to `main` cannot upload to TestFlight.

## 5. Install it on an iPhone or iPad

1. In App Store Connect, open **ByteSqueeze → TestFlight**.
2. Complete any missing export-compliance or beta-test information.
3. Create an internal testing group and add your Apple Account as a tester.
4. Add the processed build to that group.
5. Install Apple's **TestFlight** app on the iPhone or iPad.
6. Accept the invitation on the device and install ByteSqueeze.
7. On first connection, allow local-network access, enter the controller address, and pair normally.

Internal testing is the fastest path for your own devices. External testers can be added later, but the first external build may require TestFlight beta review.

## Before App Store submission

Test pairing and reconnects, controller failover addresses, queue and worker controls, Size Wizard, Smart Presets, local-network permission denial/recovery, phone rotation, iPad portrait/landscape, and iPad Split View. Also complete the App Privacy answers, privacy-policy URL, support URL, screenshots, age rating, and final export-compliance determination in App Store Connect.
