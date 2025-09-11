## Frequently Asked Questions (FAQ)

### Troubleshooting

#### Q1: When starting teh app on macOS, how do I get past the  *Detectorist.app Not Opened* message?
**A:** macOS prevents unsigned apps, but you still can [open a apps from an unknown developers](https://support.apple.com/guide/mac-help/open-a-mac-app-from-an-unknown-developer-mh40616/mac). Here's how:

1. When you attempt to open the app, a warning like this appears where you have no option to open it anyways, so just select _Done_: 

    <img src="https://github.com/user-attachments/assets/3a959f80-cc5b-4c56-846d-aeb6f6c15919" width="40%" alt="Image">

1. Once you saw the warning dialog above, check out the _System Settings_ -> _Privacy & Security_ which has a new entry. Select _Open Anyway_:

    ![Image](https://github.com/user-attachments/assets/3e88e9ae-009f-4ab3-bcd7-db560c839c7b)


3. From the Finder open the Detectorist.app again, and you'll now see the option to open the application. Select _Open Anyway_:

    <img src="https://github.com/user-attachments/assets/c032524b-f49b-41da-a993-a4b09996fee7" width="40%" alt="Image">

4. Authorize the action using fingerprint or password

    <img width="40%" alt="Image" src="https://github.com/user-attachments/assets/d7fb5a57-def2-4c9b-bd69-31486a55cc50" />
    <img width="40%" alt="Image" src="https://github.com/user-attachments/assets/9c467ac3-04fa-406e-b5f6-e598ec596791" />

From now on the application can be started like any other.


Background: For this open source application there's no valid Developer ID certificate the app could signed with. Hence you get a warning. Apple requires code signing for macOS apps to verify their integrity and origin. The Apple Developer Program membership, which provides signing certificates, [costs $99 annually](https://developer.apple.com/support/compare-memberships/).
